"""格式探测链路：魔数检测→格式判定→解析器路由改写。

核心行为：
- 通过文件头魔数特征推断真实格式，不依赖声明格式
- 置信度低于阈值时标记存疑并触发人工确认
- 探测结论直接改写解析路由的推断格式字段
"""
from __future__ import annotations

from typing import Any


_MAGIC_BYTES: dict[str, str] = {
    "EFBBBF": "csv-utf8",
    "FFFE": "csv-utf16le",
    "FEFF": "csv-utf16be",
    "504B0304": "xlsx",
    "7B0A": "jsonl",
    "7B0D": "jsonl-crlf",
    "3C3F786D6C": "xml",
    "D0CF11E0": "doc",
    "25504446": "pdf",
    "1F8B08": "gzip",
}


class MagicProbe:
    """单个魔数探测结果。"""

    def __init__(self, file_bytes_hex: str, inferred_format: str, confidence: float,
                 declared_mismatch: bool = False):
        self.file_bytes_hex = file_bytes_hex
        self.inferred_format = inferred_format
        self.confidence = confidence
        self.declared_mismatch = declared_mismatch

    def to_dict(self) -> dict[str, Any]:
        return {
            "magic_bytes": self.file_bytes_hex,
            "inferred_format": self.inferred_format,
            "confidence": self.confidence,
            "declared_mismatch": self.declared_mismatch,
        }


class FormatProbeChain:
    """格式探测链路管理器。"""

    CONFIDENCE_THRESHOLD = 0.70
    FALLBACK_FORMAT = "text-unknown"

    def __init__(self) -> None:
        self._probes: dict[str, MagicProbe] = {}
        self._overrides: dict[str, str] = {}

    def probe_format(self, file_id: str, magic_bytes_hex: str, declared_format: str = "") -> tuple[bool, str, MagicProbe | None]:
        """对文件头魔数进行格式推断。"""
        if not magic_bytes_hex:
            probe = MagicProbe("", self.FALLBACK_FORMAT, 0.0)
            self._probes[file_id] = probe
            return False, f"文件 {file_id} 魔数为空，无法探测", probe

        upper_hex = magic_bytes_hex.upper()
        best_match = self.FALLBACK_FORMAT
        best_len = 0

        for magic, fmt in _MAGIC_BYTES.items():
            if upper_hex.startswith(magic) and len(magic) > best_len:
                best_match = fmt
                best_len = len(magic)

        if best_match == self.FALLBACK_FORMAT:
            confidence = 0.15
        elif best_len >= 8:
            confidence = 0.98
        elif best_len >= 4:
            confidence = 0.85
        else:
            confidence = 0.60

        if declared_format and not self._format_matches(best_match, declared_format):
            confidence = min(confidence, 0.72)
            mismatch = True
        else:
            mismatch = False

        probe = MagicProbe(magic_bytes_hex, best_match, confidence, mismatch)
        self._probes[file_id] = probe

        if confidence < self.CONFIDENCE_THRESHOLD:
            return False, f"文件 {file_id} 探测置信度 {confidence:.2f} 低于阈值 {self.CONFIDENCE_THRESHOLD}", probe

        return True, f"文件 {file_id} 探测格式为 {best_match}，置信度 {confidence:.2f}", probe

    @staticmethod
    def _format_matches(inferred: str, declared: str) -> bool:
        """判定推断格式与声明格式是否同族。

        声明只给容器类型（csv）而魔数推断出编码细分（csv-utf8）属于口径细化，
        不算不一致；两者互不包含时才判定声明与真实格式冲突。
        """
        inferred_key = inferred.split("-")[0]
        declared_key = declared.split("-")[0]
        return inferred_key == declared_key or inferred == declared

    def override_format(self, file_id: str, manual_format: str) -> None:
        """人工覆盖探测格式。"""
        self._overrides[file_id] = manual_format

    def get_resolved_format(self, file_id: str) -> str:
        """获取最终认定格式：人工覆盖优先，其次探测结果。"""
        if file_id in self._overrides:
            return self._overrides[file_id]
        probe = self._probes.get(file_id)
        if probe:
            return probe.inferred_format
        return self.FALLBACK_FORMAT

    def get_probe(self, file_id: str) -> MagicProbe | None:
        return self._probes.get(file_id)

    def snapshot(self) -> dict[str, Any]:
        return {
            "probes": {k: v.to_dict() for k, v in self._probes.items()},
            "overrides": dict(self._overrides),
            "threshold": self.CONFIDENCE_THRESHOLD,
        }