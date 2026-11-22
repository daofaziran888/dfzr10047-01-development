"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class ParseWatermarkService(BaseModuleService):
    MODULE = "parse_watermark"
    ENTITY = "水位读数"
    OPERATION_TERM = "解析"
    LIST_FIELDS = ["水位编号", "来源渠道", "已解析至位点", "待解析数量", "最近批次", "水位推进时间", "滞后批次数", "滞后原因"]
    REQUIRED_FIELDS = ["水位编号", "来源渠道", "已解析至位点"]
    STATUS_ORDER = ["已推进", "轻微滞后", "严重滞后", "推进中断"]
    ACTION_RULES = {"推进水位": "轻微滞后", "登记滞后": "严重滞后", "标记中断": "推进中断"}
    NEGATIVE_ACTIONS = []
