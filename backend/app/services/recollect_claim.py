"""补采领办领域服务：按来源核对未闭合位点区间、签发重解析批次并登记补采执行台账，产出补采领办单数据集。"""
from __future__ import annotations

from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class RecollectClaimService(BaseModuleService):
    MODULE = "recollect_claim"
    ENTITY = "补采领办单"
    OPERATION_TERM = "补采"
    LIST_FIELDS = ["领办编号", "来源渠道", "起始位点", "截止位点", "缺口批次", "领办人", "关联重解析单", "确认结论"]
    REQUIRED_FIELDS = ["领办编号", "来源渠道", "起始位点", "截止位点"]
    STATUS_ORDER = ["待确认", "补采中", "已闭合", "已作废"]
    ACTION_RULES = {"确认领办": "补采中", "登记闭合": "已闭合", "作废领办": "已作废"}
    NEGATIVE_ACTIONS = ["作废领办"]

    CLOSED_BATCH_STATES = ("闭合", "已闭合")
    ACTIVE_CLAIM_STATES = ("待确认", "补采中")

    # ---------- 位点与缺口计算 ----------

    def _channel_positions(self, channel: str) -> list[str]:
        """该来源全部已投递位点（批次编号），按编号排序。"""
        positions = [
            str(row.get("批次编号"))
            for row in store.rows("file_intake")
            if row.get("来源渠道") == channel and row.get("批次编号")
        ]
        return sorted(positions)

    def _closed_positions(self, channel: str) -> set[str]:
        """该来源已闭合的位点集合：只认本来源批次的闭合记录，来源之间隔离。"""
        own = set(self._channel_positions(channel))
        closed: set[str] = set()
        for row in store.rows("parse_batch"):
            if str(row.get("批次状态") or "") not in self.CLOSED_BATCH_STATES:
                continue
            batch_no = str(row.get("关联投递批次") or "")
            if batch_no in own:
                closed.add(batch_no)
        return closed

    def _claimed_positions(self, channel: str) -> dict[str, str]:
        """该来源被活动领办单占用的位点 → 领办编号，用于补采资格冲突判定。"""
        claimed: dict[str, str] = {}
        for row in store.rows(self.MODULE):
            if row.get("来源渠道") != channel:
                continue
            if row.get("status") not in self.ACTIVE_CLAIM_STATES:
                continue
            for pos in str(row.get("缺口批次") or "").split(","):
                pos = pos.strip()
                if pos:
                    claimed[pos] = str(row.get("领办编号") or "")
        return claimed

    def gap_segments(self, channel: str) -> list[dict[str, Any]]:
        """计算来源的补采缺口区间：连续未闭合位点聚成一段，已闭合位点强制断开。

        已闭合位点之间即使还有缺口，区间也不得包含已经完成的一段；
        每段标注可领办/已领办/部分领办，供清单视图逐段勾选。
        """
        closed = self._closed_positions(channel)
        claimed = self._claimed_positions(channel)
        segments: list[dict[str, Any]] = []
        current: dict[str, Any] | None = None
        for pos in self._channel_positions(channel):
            if pos in closed:
                if current is not None:
                    segments.append(current)
                    current = None
                continue
            if current is None:
                current = {"来源渠道": channel, "起始位点": pos, "截止位点": pos, "缺口批次": [pos]}
            else:
                current["截止位点"] = pos
                current["缺口批次"].append(pos)
        if current is not None:
            segments.append(current)
        for seg in segments:
            held = [p for p in seg["缺口批次"] if p in claimed]
            seg["批次数"] = len(seg["缺口批次"])
            if not held:
                seg["状态"] = "可领办"
                seg["占用领办单"] = ""
            else:
                seg["状态"] = "已领办" if len(held) == len(seg["缺口批次"]) else "部分领办"
                seg["占用领办单"] = claimed[held[0]]
        return segments

    def gap_board(self) -> list[dict[str, Any]]:
        """全部来源的补采区间清单，按来源排列，供解析进度页清单视图消费。"""
        channels = sorted({
            str(row.get("来源渠道"))
            for row in store.rows("file_intake")
            if row.get("来源渠道")
        })
        return [
            {
                "来源渠道": channel,
                "segments": self.gap_segments(channel),
                "可领办段数": sum(1 for s in self.gap_segments(channel) if s["状态"] == "可领办"),
            }
            for channel in channels
        ]

    # ---------- 领办签发 ----------

    @staticmethod
    def _claim_seq(claim_no: str) -> int:
        if claim_no.startswith("RC-"):
            tail = claim_no[3:]
            return int(tail) if tail.isdigit() else 0
        return 0

    def _next_claim_no(self) -> str:
        rows = store.rows(self.MODULE)
        seq = max((self._claim_seq(str(r.get("领办编号") or "")) for r in rows), default=0) + 1
        return f"RC-{seq:03d}"

    def _register_claim(self, claim_no: str, channel: str, start: str, end: str,
                        positions: list[str], operator: str, task_no: str,
                        claim_time: str) -> dict[str, Any]:
        rows = store.rows(self.MODULE)
        entry = {
            "id": max((int(r.get("id", 0)) for r in rows), default=0) + 1,
            "status": "补采中", "pending": True, "abnormal": False,
            "领办编号": claim_no,
            "来源渠道": channel,
            "起始位点": start,
            "截止位点": end,
            "缺口批次": ",".join(positions),
            "领办人": operator,
            "关联重解析单": task_no,
            "确认结论": "",
            "领办时间": claim_time,
        }
        rows.append(entry)
        return dict(entry)

    def claim_intervals(self, channel: str, segments: list[dict[str, str]],
                        operator: str, claim_time: str) -> tuple[bool, str, dict[str, Any]]:
        """领办提交：服务端逐段核对区间，核对通过的段签发重解析批次并登记台账。

        核对规则：
        - 区间只覆盖本来源位点，批次位点相同也按来源隔离，不得带走其他来源同编号文件；
        - 区间不得包含已闭合位点，已闭合位点之间的缺口也不能含已完成的一段；
        - 同一位点补采资格唯一，不得与活动领办单重叠。
        每段独立判定：失败段进入"仍需确认"并保留原因，不影响其余段签发。
        """
        from app.services import SERVICES  # 延迟导入，避免服务注册期循环依赖
        reparse_svc = SERVICES.get("reparse_task")

        operator = (operator or "").strip()
        if not operator:
            return False, "领办人标识不能为空", {"created": [], "pending": []}
        if not segments:
            return False, "没有勾选任何补采区间", {"created": [], "pending": []}

        positions = self._channel_positions(channel)
        if not positions:
            return False, f"来源 {channel} 没有投递位点", {"created": [], "pending": []}
        closed = self._closed_positions(channel)

        created: list[dict[str, Any]] = []
        pending: list[dict[str, Any]] = []
        for seg in segments:
            start = str(seg.get("起始位点") or "").strip()
            end = str(seg.get("截止位点") or "").strip()
            seg_info = {"来源渠道": channel, "起始位点": start, "截止位点": end}
            if not start or not end or start > end:
                pending.append({**seg_info, "原因": f"区间 [{start},{end}] 起止位点非法"})
                continue
            inside = [p for p in positions if start <= p <= end]
            if not inside:
                pending.append({**seg_info, "原因": f"区间 [{start},{end}] 在来源 {channel} 下没有位点"})
                continue
            closed_inside = [p for p in inside if p in closed]
            if closed_inside:
                pending.append({**seg_info, "原因": (
                    f"区间包含已闭合位点 {','.join(closed_inside)}，"
                    f"补采区间不得包含已完成的一段"
                )})
                continue
            claimed = self._claimed_positions(channel)  # 每段重算：前面段签发后立即占用
            conflict = [p for p in inside if p in claimed]
            if conflict:
                pending.append({**seg_info, "原因": (
                    f"位点 {','.join(conflict)} 已被 {claimed[conflict[0]]} 领办，"
                    f"同一位点补采资格冲突"
                )})
                continue
            claim_no = self._next_claim_no()
            task_no = f"RT-{claim_no}"
            reason = f"补采领办 {claim_no}：来源 {channel} 位点 [{start},{end}] 缺口补采"
            position_map = {p: p for p in inside}
            ok, msg, _task = reparse_svc.plan_position_range(
                task_no, reason, reparse_svc.KEEP_OLD, inside, position_map)
            if not ok:
                pending.append({**seg_info, "原因": f"重解析批次签发失败：{msg}"})
                continue
            self._register_claim(
                claim_no, channel, start, end, inside, operator, task_no, claim_time)
            created.append({
                **seg_info, "领办编号": claim_no, "关联重解析单": task_no,
                "缺口批次": inside, "批次数": len(inside),
            })
        return bool(created), self._claim_message(created, pending), {
            "created": created, "pending": pending,
        }

    @staticmethod
    def _claim_message(created: list[dict[str, Any]], pending: list[dict[str, Any]]) -> str:
        parts: list[str] = []
        if created:
            parts.append(
                f"已签发 {len(created)} 段：" + "、".join(c["领办编号"] for c in created))
        if pending:
            parts.append(f"{len(pending)} 段仍需确认，其余勾选已保留")
        return "；".join(parts) if parts else "没有可领办的区间"

    # ---------- 位点幂等闭合 ----------

    def confirm_position_close(self, channel: str, position: str, close_source: str,
                               operator: str, close_time: str) -> tuple[bool, str, dict[str, Any] | None]:
        """位点闭合核对：同一来源同一位点只允许确认一次闭合。

        迟到原件与补采结果并发提交时先到先得；重放同一闭合请求只算一次，
        闭合计数与台账结论都不重复追加。
        """
        position = (position or "").strip()
        close_source = (close_source or "").strip() or "补采结果"
        if position not in self._channel_positions(channel):
            return False, f"位点 {position} 不属于来源 {channel}，闭合被拒绝", None
        if position in self._closed_positions(channel):
            return False, f"位点 {position} 已闭合，重复确认被拒绝（重放只算一次）", None
        batch = next(
            (r for r in store.rows("parse_batch")
             if str(r.get("关联投递批次")) == position),
            None)
        if batch is None:
            return False, f"位点 {position} 没有批次记录，无法闭合", None

        batch["批次状态"] = "已闭合"
        batch["status"] = "已闭合"
        batch["完成时间"] = close_time
        batch["pending"] = False
        batch["abnormal"] = False

        closed = self._closed_positions(channel)
        touched: list[dict[str, Any]] = []
        for claim in store.rows(self.MODULE):
            if claim.get("来源渠道") != channel:
                continue
            if claim.get("status") not in self.ACTIVE_CLAIM_STATES:
                continue
            positions = [
                p.strip() for p in str(claim.get("缺口批次") or "").split(",") if p.strip()
            ]
            if position not in positions:
                continue
            note = f"位点 {position} 由{close_source}于 {close_time} 闭合"
            conclusion = str(claim.get("确认结论") or "")
            claim["确认结论"] = (conclusion + "；" + note).strip("；")
            if all(p in closed for p in positions):
                claim["status"] = "已闭合"
                claim["pending"] = False
            touched.append(claim)
        entry = {
            "位点": position,
            "闭合来源": close_source,
            "闭合时间": close_time,
            "关联领办单": [str(c.get("领办编号")) for c in touched],
        }
        return True, (
            f"位点 {position} 已由{close_source}闭合，"
            f"关联 {len(touched)} 张领办单，重放不再计数"
        ), entry

    # ---------- 迟到原件与台账同步 ----------

    def late_original_arrival(self, channel: str, position: str,
                              arrive_time: str) -> tuple[bool, str, dict[str, Any] | None]:
        """迟到原投递写入：同一位点已被领办时标记补采资格冲突。

        冲突不阻断后续闭合：原件与补采结果任一到达后，
        仍通过 confirm_position_close 核对该位点唯一一次闭合。
        """
        position = (position or "").strip()
        if position not in self._channel_positions(channel):
            return False, f"位点 {position} 不属于来源 {channel}", None
        if position in self._closed_positions(channel):
            return False, f"位点 {position} 已闭合，迟到原件不再触发补采冲突", None
        claimed = self._claimed_positions(channel)
        claim_no = claimed.get(position)
        if claim_no is None:
            return True, f"位点 {position} 迟到原件已写入，未被领办，可直接核对闭合", {
                "conflict": False, "领办编号": "",
            }
        claim = next(
            (r for r in store.rows(self.MODULE) if r.get("领办编号") == claim_no), None)
        if claim is not None:
            claim["abnormal"] = True
            note = f"迟到原件于 {arrive_time} 到达，补采资格冲突，待闭合核对"
            conclusion = str(claim.get("确认结论") or "")
            if note not in conclusion:
                claim["确认结论"] = (conclusion + "；" + note).strip("；")
        return True, (
            f"位点 {position} 已被 {claim_no} 领办，迟到原件写入触发补采资格冲突，"
            f"原件与补采结果只允许确认一次闭合"
        ), {"conflict": True, "领办编号": claim_no}

    def sync_reparse_conclusion(self, task_no: str, conclusion: str) -> list[dict[str, Any]]:
        """重解析确认结论同步到补采执行台账：按关联重解析单找回活动领办单。"""
        synced: list[dict[str, Any]] = []
        for row in store.rows(self.MODULE):
            if str(row.get("关联重解析单") or "") != str(task_no):
                continue
            if row.get("status") not in self.ACTIVE_CLAIM_STATES:
                continue
            row["确认结论"] = conclusion
            synced.append(dict(row))
        return synced
