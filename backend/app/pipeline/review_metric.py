"""抽样复核与解析指标：偏差超限阻断→指标真实计数结算。

核心行为：
- 对已闭合批次按比例抽样，比对解析取值与原始文本
- 取值偏差率超限时驳回样本、阻断输出契约通过并触发重解析
- 隔离率来自坏行隔离管理器的真实计数，回退率来自解析路由的真实回退次数
"""
from __future__ import annotations

import random
from typing import Any


class ReviewSample:
    """单条复核样本。"""

    def __init__(self, sample_id: str, batch_id: str, sample_ratio: float,
                 reviewer: str):
        self.sample_id = sample_id
        self.batch_id = batch_id
        self.sample_ratio = sample_ratio
        self.reviewer = reviewer
        self.sampled_rows = 0
        self.consistent_count = 0
        self.deviation_count = 0
        self.conclusion = ""
        self.status = "待复核"

    @property
    def deviation_rate(self) -> float:
        if self.sampled_rows <= 0:
            return 0.0
        return self.deviation_count / self.sampled_rows

    def to_dict(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "batch_id": self.batch_id,
            "sample_ratio": self.sample_ratio,
            "reviewer": self.reviewer,
            "sampled_rows": self.sampled_rows,
            "consistent_count": self.consistent_count,
            "deviation_count": self.deviation_count,
            "deviation_rate": round(self.deviation_rate, 4),
            "conclusion": self.conclusion,
            "status": self.status,
        }


class MetricReading:
    """单条指标读数。"""

    def __init__(self, reading_id: str, window: str, channel: str,
                 throughput_rows: int, avg_parse_ms: float,
                 quarantine_rate: float, fallback_rate: float,
                 collected_at: str):
        self.reading_id = reading_id
        self.window = window
        self.channel = channel
        self.throughput_rows = throughput_rows
        self.avg_parse_ms = avg_parse_ms
        self.quarantine_rate = quarantine_rate
        self.fallback_rate = fallback_rate
        self.collected_at = collected_at
        self.status = "统计中"

    def to_dict(self) -> dict[str, Any]:
        return {
            "reading_id": self.reading_id,
            "window": self.window,
            "channel": self.channel,
            "throughput_rows": self.throughput_rows,
            "avg_parse_ms": round(self.avg_parse_ms, 3),
            "quarantine_rate": round(self.quarantine_rate, 4),
            "fallback_rate": round(self.fallback_rate, 4),
            "collected_at": self.collected_at,
            "status": self.status,
        }


class ReviewMetricEngine:
    """抽样复核与指标结算引擎。"""

    MAX_DEVIATION_RATE = 0.10

    def __init__(self, seed: int = 20260901) -> None:
        self._samples: dict[str, ReviewSample] = {}
        self._readings: dict[str, MetricReading] = {}
        self._rng = random.Random(seed)

    def run_review(self, sample_id: str, batch_id: str, parsed_rows: list[dict[str, Any]],
                   raw_rows: list[dict[str, Any]], ratio: float,
                   reviewer: str, compare_fields: list[str]) -> ReviewSample:
        """执行抽样复核：按比例抽样并逐字段比对解析取值与原始文本。"""
        sample = ReviewSample(sample_id, batch_id, ratio, reviewer)
        total = len(parsed_rows)
        sample_size = max(1, int(round(total * ratio))) if total > 0 else 0
        sample.sampled_rows = min(sample_size, total)

        if total == 0:
            sample.status = "已驳回"
            sample.conclusion = "批次无解析行，无法复核"
            self._samples[sample_id] = sample
            return sample

        indices = self._rng.sample(range(total), sample.sampled_rows)
        for idx in sorted(indices):
            parsed = parsed_rows[idx]
            raw = raw_rows[idx] if idx < len(raw_rows) else {}
            row_ok = True
            for field in compare_fields:
                p_val = parsed.get(field)
                r_val = raw.get(field)
                if p_val is None and r_val in (None, ""):
                    continue
                if str(p_val) != str(r_val) and not self._numeric_equal(p_val, r_val):
                    row_ok = False
                    break
            if row_ok:
                sample.consistent_count += 1
            else:
                sample.deviation_count += 1

        if sample.deviation_rate > self.MAX_DEVIATION_RATE:
            sample.status = "已驳回"
            sample.conclusion = (
                f"驳回:取值偏差率 {sample.deviation_rate:.1%} "
                f"超出容许上限 {self.MAX_DEVIATION_RATE:.0%}"
            )
        else:
            sample.status = "已通过"
            sample.conclusion = (
                f"通过:取值偏差率 {sample.deviation_rate:.1%} 在容许上限内"
            )
        self._samples[sample_id] = sample
        return sample

    @staticmethod
    def _numeric_equal(a: Any, b: Any) -> bool:
        """数值宽松相等：1024 与 '1024'、1024.0 与 '1024' 视为一致。"""
        try:
            return abs(float(a) - float(b)) < 1e-9
        except (TypeError, ValueError):
            return False

    def is_batch_blocked_by_review(self, batch_id: str) -> tuple[bool, str]:
        """检查批次是否被抽样复核驳回阻断（供输出契约消费）。"""
        for sample in self._samples.values():
            if sample.batch_id == batch_id and sample.status == "已驳回":
                return True, (
                    f"批次 {batch_id} 抽样复核被驳回（{sample.conclusion}），"
                    f"输出契约不得通过"
                )
        return False, ""

    def get_sample(self, sample_id: str) -> ReviewSample | None:
        return self._samples.get(sample_id)

    def collect_metric(self, reading_id: str, window: str, channel: str,
                       throughput_rows: int, parse_durations_ms: list[float],
                       quarantined_rows: int, total_rows: int,
                       fallback_decisions: int, total_decisions: int,
                       collected_at: str) -> MetricReading:
        """结算指标读数。隔离率与回退率来自真实计数而非估算。"""
        avg_ms = (
            sum(parse_durations_ms) / len(parse_durations_ms)
            if parse_durations_ms else 0.0
        )
        quarantine_rate = quarantined_rows / total_rows if total_rows > 0 else 0.0
        fallback_rate = (
            fallback_decisions / total_decisions if total_decisions > 0 else 0.0
        )
        reading = MetricReading(
            reading_id, window, channel, throughput_rows, avg_ms,
            quarantine_rate, fallback_rate, collected_at,
        )
        reading.status = "已结算"
        self._readings[reading_id] = reading
        return reading

    def get_reading(self, reading_id: str) -> MetricReading | None:
        return self._readings.get(reading_id)

    def channel_summary(self, channel: str) -> dict[str, Any]:
        """按来源渠道汇总指标。"""
        readings = [r for r in self._readings.values() if r.channel == channel]
        if not readings:
            return {"channel": channel, "reading_count": 0}
        return {
            "channel": channel,
            "reading_count": len(readings),
            "total_throughput": sum(r.throughput_rows for r in readings),
            "avg_quarantine_rate": (
                sum(r.quarantine_rate for r in readings) / len(readings)
            ),
            "avg_fallback_rate": (
                sum(r.fallback_rate for r in readings) / len(readings)
            ),
        }

    def snapshot(self) -> dict[str, Any]:
        return {
            "samples": {k: v.to_dict() for k, v in self._samples.items()},
            "readings": {k: v.to_dict() for k, v in self._readings.items()},
            "max_deviation_rate": self.MAX_DEVIATION_RATE,
        }
