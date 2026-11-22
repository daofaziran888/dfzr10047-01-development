"""格式探测领域服务：通过文件头魔数特征辨识真实文件格式，产出探测结论数据集。"""
from __future__ import annotations

from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class FormatProbeService(BaseModuleService):
    MODULE = "format_probe"
    ENTITY = "探测结论"
    OPERATION_TERM = "读取"
    LIST_FIELDS = ["探测编号", "关联批次", "魔数特征", "推断格式", "置信度", "结构层级", "是否压缩", "探测耗时"]
    REQUIRED_FIELDS = ["探测编号", "关联批次", "魔数特征"]
    STATUS_ORDER = ["待探测", "已确认", "存疑", "无法识别"]
    ACTION_RULES = {"确认格式": "已确认", "标记存疑": "存疑", "判定无法识别": "无法识别"}
    NEGATIVE_ACTIONS = ["判定无法识别"]

    # 魔数前缀 → (推断格式, 基础置信度, 是否压缩)
    MAGIC_TABLE: dict[str, tuple[str, float, bool]] = {
        "EFBBBF": ("csv-utf8", 0.98, False),
        "FFFE": ("csv-utf16le", 0.95, False),
        "FEFF": ("csv-utf16be", 0.95, False),
        "504B0304": ("xlsx", 0.90, True),
        "7B0A": ("jsonl", 0.80, False),
        "7B0D": ("jsonl-crlf", 0.80, False),
        "3C3F786D6C": ("xml", 0.92, False),
        "1F8B08": ("gzip", 0.97, True),
        "25504446": ("pdf", 0.96, False),
    }

    CONFIRM_THRESHOLD = 0.70

    def probe(self, probe_no: str, intake_batch: str, magic_hex: str,
              declared_format: str, elapsed_ms: int) -> tuple[bool, str, dict[str, Any] | None]:
        """执行魔数探测并写入探测结论。

        真实格式与声明格式不一致时置信度打折并标记存疑，
        改写解析路由输入的推断格式字段，同时回写投递批次。
        """
        upper = magic_hex.upper().strip()
        matched: tuple[str, float, bool] | None = None
        matched_len = 0
        for magic, meta in self.MAGIC_TABLE.items():
            if upper.startswith(magic) and len(magic) > matched_len:
                matched = meta
                matched_len = len(magic)

        if matched is None:
            inferred, confidence, compressed = "text-unknown", 0.15, False
        else:
            inferred, confidence, compressed = matched

        mismatch = (
            bool(declared_format)
            and inferred.split("-")[0] != declared_format.split("-")[0]
        )
        if mismatch:
            confidence = min(confidence, 0.72)

        if confidence >= self.CONFIRM_THRESHOLD and not mismatch:
            status = "已确认"
        elif confidence >= 0.5:
            status = "存疑"
        else:
            status = "无法识别"

        rows = store.rows(self.MODULE)
        entry_id = max((int(r.get("id", 0)) for r in rows), default=0) + 1
        entry = {
            "id": entry_id,
            "status": status,
            "pending": status != "已确认",
            "abnormal": status == "无法识别",
            "探测编号": probe_no,
            "关联批次": intake_batch,
            "魔数特征": upper,
            "推断格式": inferred,
            "置信度": f"{confidence:.2f}",
            "结构层级": "1" if inferred != "text-unknown" else "0",
            "是否压缩": "是" if compressed else "否",
            "探测耗时": str(elapsed_ms),
            "声明格式": declared_format,
        }
        rows.append(entry)

        # 回写投递批次的探测结果，声明格式与真实格式不一致时留痕
        for batch in store.rows("file_intake"):
            if batch.get("批次编号") != intake_batch:
                continue
            if status == "无法识别":
                batch["status"] = "探测失败"
                batch["pending"] = False
                batch["abnormal"] = True
            else:
                batch["status"] = "待探测"
                batch["pending"] = True
            batch["真实格式"] = inferred
            if mismatch:
                batch["格式改写"] = f"声明 {declared_format} → 探测 {inferred}"
            break

        message = (
            f"批次 {intake_batch} 魔数 {upper} 推断格式 {inferred}"
            f"（置信度 {confidence:.2f}，{status}）"
        )
        if mismatch:
            message += f"，与声明格式 {declared_format} 不一致，解析路由按探测格式改写"
        return status == "已确认", message, dict(entry)

    def resolved_format(self, intake_batch: str) -> str:
        """输出解析路由消费的认定格式：最新探测结论的推断格式。"""
        candidates = [
            r for r in store.rows(self.MODULE)
            if r.get("关联批次") == intake_batch
        ]
        if not candidates:
            return "text-unknown"
        latest = max(candidates, key=lambda r: int(r.get("id", 0)))
        return str(latest.get("推断格式") or "text-unknown")

    def confirm_format(self, probe_no: str, confirmed_format: str,
                       confirm_time: str) -> tuple[bool, str]:
        """人工确认存疑结论：确认后置信度提升，解析路由可继续。"""
        for row in store.rows(self.MODULE):
            if row.get("探测编号") != probe_no:
                continue
            if row.get("status") == "已确认":
                return False, f"探测结论 {probe_no} 已是确认状态"
            row["推断格式"] = confirmed_format
            row["置信度"] = "0.95"
            row["status"] = "已确认"
            row["pending"] = False
            row["abnormal"] = False
            row["确认时间"] = confirm_time
            return True, (
                f"探测结论 {probe_no} 已人工确认为 {confirmed_format}，解析路由可继续"
            )
        return False, f"探测结论 {probe_no} 不存在"

    def mismatch_batches(self) -> list[dict[str, Any]]:
        """列出声明格式与探测格式跨族不一致的批次，供投递审计留痕。"""
        return [
            {
                "探测编号": r.get("探测编号"),
                "关联批次": r.get("关联批次"),
                "声明格式": r.get("声明格式"),
                "推断格式": r.get("推断格式"),
                "置信度": r.get("置信度"),
            }
            for r in store.rows(self.MODULE)
            if r.get("声明格式")
            and str(r.get("声明格式")).split("-")[0] != str(r.get("推断格式") or "").split("-")[0]
        ]
