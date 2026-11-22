"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class ParseMetricService(BaseModuleService):
    MODULE = "parse_metric"
    ENTITY = "指标读数"
    OPERATION_TERM = "采集"
    LIST_FIELDS = ["指标读数编号", "统计窗口", "来源渠道", "解析吞吐行数", "平均解析耗时", "隔离率", "回退率", "采集时间"]
    REQUIRED_FIELDS = ["指标读数编号", "统计窗口", "来源渠道"]
    STATUS_ORDER = ["统计中", "已结算", "待复核", "已作废"]
    ACTION_RULES = {"提交结算": "已结算", "复核读数": "待复核", "作废读数": "已作废"}
    NEGATIVE_ACTIONS = ["作废读数"]
