"""解析水位与重解析引擎：来源渠道水位推进+覆盖策略重解析。

核心行为：
- 按来源渠道维护解析位点，只有该来源全部批次闭合后才可推进水位
- 滞后判定由滞后批次数推导
- 重解析任务按覆盖策略管理旧投递记录的保留/替代
"""
from __future__ import annotations

from typing import Any


class WatermarkReading:
    """单条水位读数。"""

    def __init__(self, channel: str, position: str = "", total_unparsed: int = 0):
        self.channel = channel
        self.position = position
        self.total_unparsed = total_unparsed
        self.lag_count = 0
        self.lag_reason = ""
        self.advance_time = ""
        self.all_closed = False

    def can_advance(self) -> tuple[bool, str]:
        """检查水位推进前置条件：该来源全部批次闭合。"""
        if not self.all_closed:
            return False, f"来源 {self.channel} 存在未闭合批次，无法推进水位"
        return True, ""

    def advance(self, new_position: str, advance_time: str) -> tuple[bool, str]:
        """推进水位。"""
        ok, reason = self.can_advance()
        if not ok:
            return False, reason
        self.position = new_position
        self.advance_time = advance_time
        self.lag_count = max(0, self.lag_count - self.total_unparsed)
        if self.lag_count == 0:
            self.lag_reason = ""
        return True, f"水位推进至 {new_position}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "channel": self.channel,
            "position": self.position,
            "total_unparsed": self.total_unparsed,
            "lag_count": self.lag_count,
            "lag_reason": self.lag_reason,
            "advance_time": self.advance_time,
            "all_closed": self.all_closed,
        }


class ReparseUnit:
    """单次重解析任务。"""

    def __init__(self, task_id: str, batch_id: str, reason: str,
                 coverage_strategy: str, start_position: str, end_position: str):
        self.task_id = task_id
        self.batch_id = batch_id
        self.reason = reason
        self.coverage_strategy = coverage_strategy
        self.start_position = start_position
        self.end_position = end_position
        self.affected_count = 0
        self.conclusion = ""
        self.completed = False
        self.aborted = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "batch_id": self.batch_id,
            "reason": self.reason,
            "coverage_strategy": self.coverage_strategy,
            "start_position": self.start_position,
            "end_position": self.end_position,
            "affected_count": self.affected_count,
            "conclusion": self.conclusion,
            "completed": self.completed,
            "aborted": self.aborted,
        }


class WatermarkAndReparse:
    """解析水位与重解析管理器。"""

    def __init__(self) -> None:
        self._watermarks: dict[str, WatermarkReading] = {}
        self._reparse_tasks: dict[str, ReparseUnit] = {}
        self._batch_coverage: dict[str, dict[str, str]] = {}

    def register_channel(self, channel: str, total_unparsed: int = 0) -> WatermarkReading:
        if channel not in self._watermarks:
            self._watermarks[channel] = WatermarkReading(channel, "", total_unparsed)
        return self._watermarks[channel]

    def mark_batch_closed(self, channel: str, batch_id: str) -> None:
        """标记批次闭合，当来源下全部批次闭合后水位可推进。"""
        wm = self._watermarks.get(channel)
        if wm is None:
            return
        wm.total_unparsed = max(0, wm.total_unparsed - 1)
        if wm.total_unparsed == 0:
            wm.all_closed = True

    def advance_watermark(self, channel: str, new_position: str,
                          advance_time: str) -> tuple[bool, str]:
        wm = self._watermarks.get(channel)
        if wm is None:
            self.register_channel(channel)
            wm = self._watermarks[channel]
        return wm.advance(new_position, advance_time)

    def set_lag(self, channel: str, lag_count: int, reason: str) -> None:
        wm = self._watermarks.get(channel)
        if wm is None:
            self.register_channel(channel, lag_count)
            wm = self._watermarks[channel]
        wm.lag_count = lag_count
        wm.lag_reason = reason

    def get_watermark(self, channel: str) -> WatermarkReading | None:
        return self._watermarks.get(channel)

    def create_reparse(self, task_id: str, batch_id: str, reason: str,
                       coverage_strategy: str, start_position: str,
                       end_position: str, affected_count: int = 0) -> tuple[bool, str, ReparseUnit | None]:
        """创建重解析任务。"""
        if task_id in self._reparse_tasks:
            task = self._reparse_tasks[task_id]
            return False, f"重解析任务 {task_id} 已存在", None

        task = ReparseUnit(task_id, batch_id, reason, coverage_strategy,
                           start_position, end_position)
        task.affected_count = affected_count
        self._reparse_tasks[task_id] = task
        return True, f"重解析任务 {task_id} 已创建", task

    def complete_reparse(self, task_id: str, conclusion: str,
                         affected_count: int) -> tuple[bool, str]:
        """完成重解析任务。"""
        task = self._reparse_tasks.get(task_id)
        if task is None:
            return False, f"重解析任务 {task_id} 不存在"
        if task.aborted:
            return False, f"任务 {task_id} 已被中止无法完成"
        task.conclusion = conclusion
        task.affected_count = affected_count
        task.completed = True
        return True, f"重解析任务 {task_id} 已完成"

    def abort_reparse(self, task_id: str, reason: str) -> tuple[bool, str]:
        """中止重解析任务。"""
        task = self._reparse_tasks.get(task_id)
        if task is None:
            return False, f"重解析任务 {task_id} 不存在"
        if task.completed:
            return False, f"任务 {task_id} 已完成不能中止"
        task.aborted = True
        task.conclusion = reason
        return True, f"重解析任务 {task_id} 已中止: {reason}"

    def register_coverage(self, batch_id: str, coverage_strategy: str,
                          old_deliver_id: str) -> None:
        """登记批次覆盖策略对应的旧投递处理。"""
        self._batch_coverage.setdefault(batch_id, {})[old_deliver_id] = coverage_strategy

    def get_coverage(self, batch_id: str) -> dict[str, str]:
        return self._batch_coverage.get(batch_id, {})

    def snapshot(self) -> dict[str, Any]:
        return {
            "watermarks": {k: v.to_dict() for k, v in self._watermarks.items()},
            "reparse_tasks": {k: v.to_dict() for k, v in self._reparse_tasks.items()},
            "coverage": dict(self._batch_coverage),
        }