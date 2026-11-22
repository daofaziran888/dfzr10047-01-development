"""重复指纹领域服务：为每个批次计算内容与结构哈希并裁定重复判定，产出指纹记录数据集。"""
from __future__ import annotations

import hashlib
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class DupFingerprintService(BaseModuleService):
    MODULE = "dup_fingerprint"
    ENTITY = "指纹记录"
    OPERATION_TERM = "去重"
    LIST_FIELDS = ["指纹编号", "关联批次", "内容指纹", "结构指纹", "命中重复批次", "重复判定", "去重处置", "判定时间"]
    REQUIRED_FIELDS = ["指纹编号", "关联批次", "内容指纹"]
    STATUS_ORDER = ["已计算", "疑似重复", "确认重复", "判定唯一"]
    ACTION_RULES = {"计算指纹": "疑似重复", "确认重复": "确认重复", "判定唯一": "判定唯一"}
    NEGATIVE_ACTIONS = ["确认重复"]

    @staticmethod
    def content_fingerprint(raw_lines: list[str]) -> str:
        """内容指纹：全部行文本的 SHA256 前 16 位。"""
        joined = "\n".join(raw_lines)
        return "sha256:" + hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def structure_fingerprint(column_names: list[str]) -> str:
        """结构指纹：排序后列名清单的 MD5 前 16 位。"""
        joined = "|".join(sorted(column_names))
        return "md5:" + hashlib.md5(joined.encode("utf-8")).hexdigest()[:16]

    def compute_and_judge(self, fingerprint_no: str, intake_batch: str,
                          raw_lines: list[str], column_names: list[str],
                          judge_time: str) -> tuple[str, dict[str, Any]]:
        """计算双指纹并按索引裁定重复：内容重复/结构相同内容不同/唯一。"""
        content = self.content_fingerprint(raw_lines)
        schema = self.structure_fingerprint(column_names)
        rows = store.rows(self.MODULE)

        content_hit = next(
            (r for r in rows
             if r.get("内容指纹") == content and r.get("关联批次") != intake_batch),
            None)
        schema_hit = next(
            (r for r in rows
             if r.get("结构指纹") == schema and r.get("关联批次") != intake_batch),
            None)

        if content_hit is not None:
            verdict, disposition, status = "内容重复", "阻断投递", "确认重复"
            duplicate_of = content_hit.get("关联批次", "")
        elif schema_hit is not None:
            verdict, disposition, status = "结构相同内容不同", "待人工确认", "疑似重复"
            duplicate_of = schema_hit.get("关联批次", "")
        else:
            verdict, disposition, status = "唯一", "放行", "判定唯一"
            duplicate_of = ""

        target = next((r for r in rows if r.get("指纹编号") == fingerprint_no), None)
        if target is None:
            entry_id = max((int(r.get("id", 0)) for r in rows), default=0) + 1
            target = {"id": entry_id, "指纹编号": fingerprint_no}
            rows.append(target)
        target.update({
            "关联批次": intake_batch,
            "内容指纹": content,
            "结构指纹": schema,
            "命中重复批次": duplicate_of,
            "重复判定": verdict,
            "去重处置": disposition,
            "判定时间": judge_time,
            "status": status,
            "pending": status == "疑似重复",
            "abnormal": verdict == "内容重复",
        })
        return verdict, dict(target)

    def blocks_deliver(self, intake_batch: str) -> tuple[bool, str]:
        """命中重复的批次不再触发结果投递。"""
        for row in store.rows(self.MODULE):
            if row.get("关联批次") != intake_batch:
                continue
            disposition = row.get("去重处置")
            if disposition == "阻断投递":
                return True, (
                    f"批次 {intake_batch} 内容指纹命中重复批次 "
                    f"{row.get('命中重复批次')}，结果投递已阻断"
                )
            if disposition == "待人工确认":
                return True, (
                    f"批次 {intake_batch} 结构指纹与 {row.get('命中重复批次')} 碰撞待确认，"
                    f"暂不触发投递"
                )
        return False, f"批次 {intake_batch} 指纹判定唯一，允许投递"

    def confirm_duplicate(self, fingerprint_no: str, confirm_time: str) -> tuple[bool, str]:
        """把疑似重复人工确认为重复，处置升级为阻断投递。"""
        for row in store.rows(self.MODULE):
            if row.get("指纹编号") != fingerprint_no:
                continue
            if row.get("status") == "确认重复":
                return False, f"指纹记录 {fingerprint_no} 已是确认重复状态"
            row["重复判定"] = "内容重复"
            row["去重处置"] = "阻断投递"
            row["status"] = "确认重复"
            row["pending"] = False
            row["abnormal"] = True
            row["确认时间"] = confirm_time
            return True, (
                f"指纹记录 {fingerprint_no} 已确认重复，"
                f"批次 {row.get('关联批次')} 的投递被阻断"
            )
        return False, f"指纹记录 {fingerprint_no} 不存在"

    def judge_unique(self, fingerprint_no: str) -> tuple[bool, str]:
        """把疑似重复人工判定为唯一，解除投递阻断。"""
        for row in store.rows(self.MODULE):
            if row.get("指纹编号") != fingerprint_no:
                continue
            if row.get("status") == "确认重复":
                return False, f"指纹记录 {fingerprint_no} 已确认重复，不能改判唯一"
            row["重复判定"] = "唯一"
            row["去重处置"] = "放行"
            row["status"] = "判定唯一"
            row["pending"] = False
            row["abnormal"] = False
            return True, f"指纹记录 {fingerprint_no} 已判定唯一，投递解除阻断"
        return False, f"指纹记录 {fingerprint_no} 不存在"

    def duplicate_groups(self) -> list[dict[str, Any]]:
        """按内容指纹分组输出重复批次簇，供去重报表消费。"""
        groups: dict[str, list[str]] = {}
        for row in store.rows(self.MODULE):
            key = str(row.get("内容指纹") or "")
            if key:
                groups.setdefault(key, []).append(str(row.get("关联批次")))
        return [
            {"content_fingerprint": fp, "batches": sorted(batches), "size": len(batches)}
            for fp, batches in groups.items() if len(batches) > 1
        ]
