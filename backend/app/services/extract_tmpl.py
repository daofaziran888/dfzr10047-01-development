"""抽取模板领域服务：维护按格式区分版本的字段映射配置和过渡策略，产出模板版本数据集。"""
from __future__ import annotations

from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class ExtractTmplService(BaseModuleService):
    MODULE = "extract_tmpl"
    ENTITY = "模板版本"
    OPERATION_TERM = "标准化"
    LIST_FIELDS = ["模板编号", "模板名称", "适用格式", "版本号", "抽取表达式数", "父版本号", "生效时间", "最近命中"]
    REQUIRED_FIELDS = ["模板编号", "模板名称", "适用格式"]
    STATUS_ORDER = ["草稿", "过渡中", "已生效", "已废止"]
    ACTION_RULES = {"启动过渡": "过渡中", "生效模板": "已生效", "废止模板": "已废止"}
    NEGATIVE_ACTIONS = ["废止模板"]

    def _same_lineage(self, row: dict[str, Any], name: str, fmt: str) -> bool:
        return row.get("模板名称") == name and row.get("适用格式") == fmt

    def start_transition(self, template_no: str, effective_from: str) -> tuple[bool, str, list[str]]:
        """启动过渡：目标版本进入过渡中，同族已生效版本继续并存可命中。

        返回过渡期内并存的全部版本号，供解析批次记录实际命中版本。
        """
        target = None
        for row in store.rows(self.MODULE):
            if row.get("模板编号") == template_no:
                target = row
                break
        if target is None:
            return False, f"模板 {template_no} 不存在", []
        if target.get("status") == "已生效":
            return False, f"模板 {template_no}[{target.get('版本号')}] 已生效，无需启动过渡", []
        if target.get("status") == "已废止":
            return False, f"模板 {template_no} 已废止，不能重新进入过渡", []

        parent_no = target.get("父版本号", "")
        if parent_no:
            parent = next(
                (r for r in store.rows(self.MODULE)
                 if r.get("版本号") == parent_no
                 and self._same_lineage(r, target["模板名称"], target["适用格式"])),
                None)
            if parent is None:
                return False, (
                    f"模板 {template_no} 声明的父版本 {parent_no} 在同族中不存在，"
                    f"版本链断裂不得启动过渡"
                ), []

        target["生效时间"] = effective_from
        target["status"] = "过渡中"
        target["pending"] = True
        target["abnormal"] = False
        coexisting = self.coexisting_versions(target["模板名称"], target["适用格式"])
        return True, (
            f"模板 {target['模板名称']}[{target['版本号']}] 进入过渡期，"
            f"并存版本 {coexisting}"
        ), coexisting

    def coexisting_versions(self, name: str, fmt: str) -> list[str]:
        """列出同族当前并存（过渡中 + 已生效）的版本号。"""
        return sorted(
            r.get("版本号", "") for r in store.rows(self.MODULE)
            if self._same_lineage(r, name, fmt)
            and r.get("status") in ("过渡中", "已生效")
        )

    def resolve_hit_version(self, name: str, fmt: str, batch_time: str) -> str | None:
        """过渡期内为批次选择命中版本：生效时间不晚于批次时间的最新版本。"""
        candidates = [
            r for r in store.rows(self.MODULE)
            if self._same_lineage(r, name, fmt)
            and r.get("status") in ("过渡中", "已生效")
        ]
        if not candidates:
            return None
        eligible = [
            r for r in candidates
            if r.get("生效时间") and r.get("生效时间") <= batch_time
        ]
        pool = eligible or candidates
        chosen = max(pool, key=lambda r: (r.get("生效时间") or "", r.get("版本号") or ""))
        return chosen.get("模板编号")

    def record_hit(self, template_no: str, batch_id: str, hit_time: str) -> tuple[bool, str]:
        """登记模板最近命中批次，供解析批次追溯实际命中版本。"""
        for row in store.rows(self.MODULE):
            if row.get("模板编号") == template_no:
                row["最近命中"] = hit_time
                row["命中批次"] = batch_id
                return True, f"模板 {template_no} 记录命中批次 {batch_id}"
        return False, f"模板 {template_no} 不存在"

    def retire_version(self, template_no: str) -> tuple[bool, str]:
        """废止模板版本：过渡结束后旧版本废止，不再参与命中选择。"""
        for row in store.rows(self.MODULE):
            if row.get("模板编号") == template_no:
                if row.get("status") == "已废止":
                    return False, f"模板 {template_no} 已处于废止状态"
                row["status"] = "已废止"
                row["pending"] = False
                row["abnormal"] = True
                return True, f"模板 {template_no}[{row.get('版本号')}] 已废止"
        return False, f"模板 {template_no} 不存在"

    def transition_report(self, name: str, fmt: str) -> dict[str, Any]:
        """输出同族版本过渡报告，供模板差异与重解析消费。"""
        rows = [r for r in store.rows(self.MODULE) if self._same_lineage(r, name, fmt)]
        return {
            "模板名称": name,
            "适用格式": fmt,
            "version_total": len(rows),
            "coexisting": self.coexisting_versions(name, fmt),
            "retired": [r.get("版本号") for r in rows if r.get("status") == "已废止"],
            "draft": [r.get("版本号") for r in rows if r.get("status") == "草稿"],
            "expression_sum": sum(
                int(r.get("抽取表达式数")) for r in rows
                if str(r.get("抽取表达式数") or "").strip().isdigit()
            ),
        }
