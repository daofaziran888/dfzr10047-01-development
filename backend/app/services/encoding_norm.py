"""编码归一领域服务：将异构来源文本统一到目标编码表，产出转码记录数据集。"""
from __future__ import annotations

from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class EncodingNormService(BaseModuleService):
    MODULE = "encoding_norm"
    ENTITY = "转码记录"
    OPERATION_TERM = "标准化"
    LIST_FIELDS = ["转码编号", "关联批次", "原始编码", "目标编码", "不可映射字符数", "替换策略", "转码后字节", "转码耗时"]
    REQUIRED_FIELDS = ["转码编号", "关联批次", "原始编码"]
    STATUS_ORDER = ["待转码", "转码中", "已完成", "存在损字"]
    ACTION_RULES = {"启动转码": "转码中", "确认完成": "已完成", "登记损字": "存在损字"}
    NEGATIVE_ACTIONS = ["登记损字"]

    REPLACE = "REPLACE"
    IGNORE = "IGNORE"
    STRICT = "STRICT"
    STRATEGIES = (REPLACE, IGNORE, STRICT)

    # 超过该比例即判定为严重损字，字段解析不得直接读取转码结果
    LOSSY_RATIO = 0.05

    def transcode(self, raw_bytes: bytes, source_encoding: str,
                  target_encoding: str, strategy: str) -> tuple[bool, bytes, int, str]:
        """执行真实转码，返回 (是否无损, 转码后字节, 不可映射字符数, 结论)。

        STRICT 策略下遇到不可映射字符直接失败，不产出半成品文本；
        REPLACE 用占位符替换并计数，IGNORE 直接丢弃并计数。
        """
        if strategy not in self.STRATEGIES:
            return False, b"", 0, f"替换策略「{strategy}」不在允许范围 {list(self.STRATEGIES)}"

        try:
            text = raw_bytes.decode(source_encoding)
        except (UnicodeDecodeError, LookupError) as exc:
            return False, b"", 0, (
                f"原始编码 {source_encoding} 解码失败: {exc}"
            )

        if strategy == self.STRICT:
            try:
                encoded = text.encode(target_encoding)
                return True, encoded, 0, (
                    f"{source_encoding}→{target_encoding} 严格转码无损，{len(encoded)} 字节"
                )
            except UnicodeEncodeError as exc:
                return False, b"", 0, (
                    f"STRICT 策略下存在不可映射字符，转码中止: {exc}"
                )

        errors = "replace" if strategy == self.REPLACE else "ignore"
        encoded = text.encode(target_encoding, errors=errors)
        roundtrip = encoded.decode(target_encoding, errors="replace")
        unmappable = sum(
            1 for original, converted in zip(text, roundtrip)
            if original != converted
        )
        if unmappable == 0:
            return True, encoded, 0, (
                f"{source_encoding}→{target_encoding} 转码完成，无不可映射字符"
            )
        return False, encoded, unmappable, (
            f"{source_encoding}→{target_encoding} 存在 {unmappable} 个不可映射字符"
            f"（策略 {strategy}）"
        )

    def record_transcode(self, norm_no: str, intake_batch: str, raw_bytes: bytes,
                         source_encoding: str, target_encoding: str,
                         strategy: str, elapsed_ms: int) -> tuple[bool, str, dict[str, Any] | None]:
        """执行转码并把真实计数写入转码记录，同时登记不可映射字符所在行。"""
        ok, encoded, unmappable, message = self.transcode(
            raw_bytes, source_encoding, target_encoding, strategy)

        rows = store.rows(self.MODULE)
        entry_id = max((int(r.get("id", 0)) for r in rows), default=0) + 1
        total_chars = len(raw_bytes.decode(source_encoding, errors="replace")) or 1
        lossy_ratio = unmappable / total_chars
        severe = unmappable > 0 and lossy_ratio > self.LOSSY_RATIO

        entry = {
            "id": entry_id,
            "status": ("已完成" if unmappable == 0 else "存在损字"),
            "pending": unmappable > 0,
            "abnormal": severe,
            "转码编号": norm_no,
            "关联批次": intake_batch,
            "原始编码": source_encoding,
            "目标编码": target_encoding,
            "不可映射字符数": str(unmappable),
            "替换策略": strategy,
            "转码后字节": str(len(encoded)),
            "转码耗时": str(elapsed_ms),
            "损字比例": f"{lossy_ratio:.4f}",
            "转码结论": message,
        }
        rows.append(entry)

        if severe:
            self._register_lossy_lines(intake_batch, raw_bytes, source_encoding,
                                       target_encoding, strategy)
            return False, (
                f"{message}，损字比例 {lossy_ratio:.2%} 超过 {self.LOSSY_RATIO:.0%}，"
                f"字段解析不得直接读取转码结果"
            ), dict(entry)
        return ok, message, dict(entry)

    def _register_lossy_lines(self, intake_batch: str, raw_bytes: bytes,
                              source_encoding: str, target_encoding: str,
                              strategy: str) -> list[str]:
        """把含不可映射字符的行登记为隔离行，隔离范围由损字位置决定。"""
        text = raw_bytes.decode(source_encoding, errors="replace")
        encoded = text.encode(target_encoding, errors="replace")
        decoded = encoded.decode(target_encoding, errors="replace")
        created: list[str] = []
        quarantine_rows = store.rows("row_quarantine")
        for index, (original_line, converted_line) in enumerate(
                zip(text.splitlines(), decoded.splitlines()), start=1):
            if original_line == converted_line:
                continue
            quarantine_no = f"RQ-{intake_batch}-enc-{index}"
            if any(r.get("隔离编号") == quarantine_no for r in quarantine_rows):
                continue
            entry_id = max((int(r.get("id", 0)) for r in quarantine_rows), default=0) + 1
            quarantine_rows.append({
                "id": entry_id, "status": "已隔离", "pending": True, "abnormal": True,
                "隔离编号": quarantine_no, "关联批次": intake_batch,
                "原始行号": str(index), "失败字段": "encoding",
                "失败原因": (
                    f"编码归一产生不可映射字符（{source_encoding}→{target_encoding}，"
                    f"策略 {strategy}）"
                ),
                "原始行文本": original_line, "复核结论": "",
                "隔离时间": "",
            })
            created.append(quarantine_no)
        return created

    def lossy_scope(self, norm_no: str) -> dict[str, Any]:
        """输出损字范围，供坏行隔离确定隔离行清单。"""
        intake_batch = ""
        unmappable = 0
        for row in store.rows(self.MODULE):
            if row.get("转码编号") == norm_no:
                intake_batch = str(row.get("关联批次") or "")
                text = str(row.get("不可映射字符数") or "0").strip()
                unmappable = int(text) if text.isdigit() else 0
                break
        isolated = [
            {"隔离编号": r.get("隔离编号"), "原始行号": r.get("原始行号")}
            for r in store.rows("row_quarantine")
            if r.get("关联批次") == intake_batch
            and "enc" in str(r.get("隔离编号") or "")
        ]
        return {
            "转码编号": norm_no,
            "关联批次": intake_batch,
            "不可映射字符数": unmappable,
            "隔离行数": len(isolated),
            "隔离行": isolated,
        }

    def blocks_field_parse(self, intake_batch: str) -> tuple[bool, str]:
        """严重损字的批次不得直接进入字段解析。"""
        for row in store.rows(self.MODULE):
            if row.get("关联批次") != intake_batch:
                continue
            if row.get("abnormal"):
                return True, (
                    f"批次 {intake_batch} 转码损字比例 {row.get('损字比例')} 超限，"
                    f"字段解析需先处理损字行"
                )
        return False, f"批次 {intake_batch} 转码结果可供字段解析读取"
