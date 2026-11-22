"""结果投递管理器：契约验证→目标写入→投递回执→重试管理。

核心行为：
- 只有通过输出契约校验的批次才触发投递
- 已确认送达的投递记录不得被覆盖（重解析时的关键约束）
- 部分送达支持重试补投缺失行数
"""
from __future__ import annotations

from typing import Any


class DeliverRecord:
    """单次投递记录。"""

    def __init__(self, record_id: str, contract_id: str, target_path: str,
                 row_count: int, output_format: str, retry_count: int = 0):
        self.record_id = record_id
        self.contract_id = contract_id
        self.target_path = target_path
        self.row_count = row_count
        self.output_format = output_format
        self.retry_count = retry_count
        self.conclusion = ""
        self.delivered = False
        self.deliver_time = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "contract_id": self.contract_id,
            "target_path": self.target_path,
            "row_count": self.row_count,
            "output_format": self.output_format,
            "retry_count": self.retry_count,
            "conclusion": self.conclusion,
            "delivered": self.delivered,
            "deliver_time": self.deliver_time,
        }


class ResultDeliverManager:
    """结果投递管理器。"""

    MAX_RETRIES = 3

    def __init__(self) -> None:
        self._records: dict[str, DeliverRecord] = {}
        self._delivered_set: set[str] = set()

    def create_deliver(self, record_id: str, contract_id: str,
                       target_path: str, row_count: int,
                       output_format: str) -> DeliverRecord:
        """创建投递记录。"""
        record = DeliverRecord(record_id, contract_id, target_path,
                               row_count, output_format, 0)
        self._records[record_id] = record
        return record

    def is_delivered(self, target_path: str) -> bool:
        """检查目标位置是否已有已确认送达的投递记录。"""
        return target_path in self._delivered_set

    def deliver(self, record_id: str, deliver_time: str,
                simulate_partial: int = 0) -> tuple[bool, str, DeliverRecord | None]:
        """执行投递。
        
        simulate_partial > 0 模拟部分送达行为：表示未送达行数。
        """
        record = self._records.get(record_id)
        if record is None:
            return False, f"投递记录 {record_id} 不存在", None

        if self.is_delivered(record.target_path):
            record.conclusion = "目标位置已有送达记录，本次投递跳过"
            return True, record.conclusion, record

        if simulate_partial > 0:
            effective_rows = record.row_count - simulate_partial
            record.retry_count += 1
            if effective_rows <= 0:
                record.conclusion = f"投递失败:模拟写入0/{record.row_count}行(重试{record.retry_count})"
                return False, record.conclusion, record
            record.conclusion = f"部分送达:{effective_rows}/{record.row_count}行写入成功(重试{record.retry_count})"
            record.deliver_time = deliver_time
            return True, record.conclusion, record

        record.delivered = True
        record.conclusion = f"成功投递:{record.row_count}行写入 {record.target_path}"
        record.deliver_time = deliver_time
        self._delivered_set.add(record.target_path)
        return True, record.conclusion, record

    def retry_deliver(self, record_id: str, deliver_time: str,
                      missing_rows: int) -> tuple[bool, str, DeliverRecord | None]:
        """重试投递缺失行。"""
        record = self._records.get(record_id)
        if record is None:
            return False, f"投递记录 {record_id} 不存在", None

        if record.retry_count >= self.MAX_RETRIES:
            record.conclusion = f"重试次数 {record.retry_count} 已达上限 {self.MAX_RETRIES}"
            return False, record.conclusion, record

        if self.is_delivered(record.target_path) and not missing_rows:
            record.conclusion = "已完成送达"
            return True, record.conclusion, record

        record.retry_count += 1
        if missing_rows == 0:
            record.delivered = True
            self._delivered_set.add(record.target_path)
            record.conclusion = f"重试成功:全部{record.row_count}行已送达"
        else:
            record.conclusion = f"重试后仍有{missing_rows}行未送达(重试{record.retry_count})"

        record.deliver_time = deliver_time
        return True, record.conclusion, record

    def get_record(self, record_id: str) -> DeliverRecord | None:
        return self._records.get(record_id)

    def snapshot(self) -> dict[str, Any]:
        return {
            "records": {k: v.to_dict() for k, v in self._records.items()},
            "delivered_targets": sorted(self._delivered_set),
        }