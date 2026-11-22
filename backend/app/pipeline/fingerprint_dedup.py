"""重复指纹检测器：内容+结构哈希→去重判定→结果投递阻断。

核心行为：
- 为每个批次计算内容指纹与结构指纹（双指纹模式）
- 内容相同直接判定重复并阻断投递
- 结构相同内容不同标记为疑似重复，待人工确认
"""
from __future__ import annotations

import hashlib
from typing import Any


class FingerprintRecord:
    """单条指纹记录。"""

    def __init__(self, record_id: str, batch_id: str, content_hash: str,
                 schema_hash: str):
        self.record_id = record_id
        self.batch_id = batch_id
        self.content_hash = content_hash
        self.schema_hash = schema_hash
        self.duplicate_of: str = ""
        self.verdict = ""
        self.disposition = ""
        self.checked_at = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "batch_id": self.batch_id,
            "content_hash": self.content_hash,
            "schema_hash": self.schema_hash,
            "duplicate_of": self.duplicate_of,
            "verdict": self.verdict,
            "disposition": self.disposition,
            "checked_at": self.checked_at,
        }


class FingerprintDedup:
    """重复指纹检测去重器。"""

    def __init__(self) -> None:
        self._records: dict[str, FingerprintRecord] = {}
        self._content_index: dict[str, str] = {}
        self._schema_index: dict[str, list[str]] = {}

    @staticmethod
    def compute_content_hash(raw_lines: list[str]) -> str:
        """计算内容指纹：SHA256。"""
        combined = "\n".join(raw_lines)
        return "sha256:" + hashlib.sha256(combined.encode()).hexdigest()[:16]

    @staticmethod
    def compute_schema_hash(column_names: list[str]) -> str:
        """计算结构指纹：列名 MD5。"""
        combined = "|".join(sorted(column_names))
        return "md5:" + hashlib.md5(combined.encode()).hexdigest()[:16]

    def check_duplicate(self, record_id: str, batch_id: str,
                        content_hash: str, schema_hash: str,
                        check_time: str) -> FingerprintRecord:
        """执行去重检查。"""
        record = FingerprintRecord(record_id, batch_id, content_hash, schema_hash)
        record.checked_at = check_time

        # 内容指纹碰撞 → 确认重复
        existing = self._content_index.get(content_hash)
        if existing:
            record.duplicate_of = existing
            record.verdict = "内容重复"
            record.disposition = "阻断投递"
            self._records[record_id] = record
            return record

        # 结构指纹碰撞（但内容不同）→ 疑似重复
        same_schema = self._schema_index.get(schema_hash, [])
        if same_schema:
            record.duplicate_of = same_schema[0]
            record.verdict = "结构相同内容不同"
            record.disposition = "待人工确认"
            self._records[record_id] = record
            self._schema_index[schema_hash].append(batch_id)
            return record

        # 无碰撞 → 判定唯一
        record.verdict = "唯一"
        record.disposition = "放行"
        self._records[record_id] = record
        self._content_index[content_hash] = batch_id
        self._schema_index.setdefault(schema_hash, []).append(batch_id)
        return record

    def is_deliver_blocked(self, batch_id: str) -> tuple[bool, str]:
        """检查指定批次是否因重复指纹被阻断投递。"""
        for record in self._records.values():
            if record.batch_id == batch_id:
                if record.disposition == "阻断投递":
                    return True, f"批次 {batch_id} 命中重复指纹（{record.duplicate_of}），投递已阻断"
                if record.disposition == "待人工确认":
                    return True, f"批次 {batch_id} 结构指纹碰撞待确认，暂不触发投递"
                return False, ""
        return False, ""

    def get_record(self, record_id: str) -> FingerprintRecord | None:
        return self._records.get(record_id)

    def snapshot(self) -> dict[str, Any]:
        records = {k: v.to_dict() for k, v in self._records.items()}
        content_size = len(self._content_index)
        schema_size = len(self._schema_index)
        return {
            "records": records,
            "content_index_size": content_size,
            "schema_index_size": schema_size,
        }