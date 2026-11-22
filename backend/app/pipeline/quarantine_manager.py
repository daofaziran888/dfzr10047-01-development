"""坏行隔离管理器：解析失败行归集、复核流转、回补决策。

核心行为：
- 接收字段解析引擎输出的失败字段列表，按行归集隔离
- 复核通过的隔离行按原始行号回补到对应解析批次
- 未复核行阻断输出契约通过
"""
from __future__ import annotations

from typing import Any


class QuarantineRow:
    """单条隔离行记录。"""

    def __init__(self, row_num: int, batch_id: str, raw_text: str,
                 failed_fields: list[str], reasons: list[str]):
        self.row_num = row_num
        self.batch_id = batch_id
        self.raw_text = raw_text
        self.failed_fields = failed_fields
        self.reasons = reasons
        self.reviewed = False
        self.review_conclusion = ""
        self.reinstated = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "row_num": self.row_num,
            "batch_id": self.batch_id,
            "raw_text": self.raw_text[:200],
            "failed_fields": self.failed_fields,
            "reasons": self.reasons,
            "reviewed": self.reviewed,
            "review_conclusion": self.review_conclusion,
            "reinstated": self.reinstated,
        }


class QuarantineManager:
    """坏行隔离管理器。"""

    MAX_QUARANTINE_RATE = 0.50

    def __init__(self) -> None:
        self._quarantines: dict[str, list[QuarantineRow]] = {}
        self._reinstated: dict[str, dict[int, dict[str, Any]]] = {}

    def quarantine_row(self, batch_id: str, row_num: int, raw_text: str,
                       failed_fields: list[dict[str, str]]) -> QuarantineRow:
        """将解析失败行隔离登记。"""
        fields = [f["field_name"] for f in failed_fields]
        reasons = [f.get("error_reason", "未知失败") for f in failed_fields]
        qr = QuarantineRow(row_num, batch_id, raw_text, fields, reasons)
        self._quarantines.setdefault(batch_id, []).append(qr)
        return qr

    def get_quarantined(self, batch_id: str) -> list[QuarantineRow]:
        return self._quarantines.get(batch_id, [])

    def quarantine_rate(self, batch_id: str, total_rows: int) -> float:
        """计算隔离率：隔离行数 / 总行数。"""
        if total_rows <= 0:
            return 1.0
        return len(self.get_quarantined(batch_id)) / total_rows

    def is_batch_blocked(self, batch_id: str, total_rows: int) -> tuple[bool, str]:
        """判断批次是否被隔离阻断：隔离率超过阈值时必须介入。"""
        rate = self.quarantine_rate(batch_id, total_rows)
        if rate > self.MAX_QUARANTINE_RATE:
            return True, f"批次 {batch_id} 隔离率 {rate:.1%} 超过 {self.MAX_QUARANTINE_RATE:.0%} 阻断阈值"
        return False, f"隔离率 {rate:.1%} 在允许范围内"

    def review_row(self, batch_id: str, row_num: int, conclusion: str,
                   corrected_values: dict[str, Any] | None = None) -> bool:
        """复核隔离行：通过则回补，拒绝则保留废弃状态。"""
        for qr in self._quarantines.get(batch_id, []):
            if qr.row_num == row_num:
                qr.reviewed = True
                qr.review_conclusion = conclusion
                if conclusion == "回补" and corrected_values:
                    qr.reinstated = True
                    self._reinstated.setdefault(batch_id, {})[row_num] = corrected_values
                return True
        return False

    def get_reinstated(self, batch_id: str) -> dict[int, dict[str, Any]]:
        """获取指定批次已回补的隔离行数据。"""
        return self._reinstated.get(batch_id, {})

    def get_unreviewed_count(self, batch_id: str) -> int:
        """未复核隔离行数（阻断输出契约的依据）。"""
        return sum(1 for qr in self._quarantines.get(batch_id, []) if not qr.reviewed)

    def quarantine_summary(self, batch_id: str) -> dict[str, Any]:
        """隔离状态摘要。"""
        qrs = self.get_quarantined(batch_id)
        return {
            "batch_id": batch_id,
            "total_quarantined": len(qrs),
            "reviewed": sum(1 for qr in qrs if qr.reviewed),
            "reinstated": sum(1 for qr in qrs if qr.reinstated),
            "unreviewed": sum(1 for qr in qrs if not qr.reviewed),
            "rows": [qr.to_dict() for qr in qrs],
        }

    def snapshot(self) -> dict[str, Any]:
        return {
            k: self.quarantine_summary(k) for k in self._quarantines
        }