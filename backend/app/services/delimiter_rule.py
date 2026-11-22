"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class DelimiterRuleService(BaseModuleService):
    MODULE = "delimiter_rule"
    ENTITY = "规则条目"
    OPERATION_TERM = "切分"
    LIST_FIELDS = ["规则编号", "适用格式", "分隔符", "引号字符", "转义字符", "换行识别", "命中批次数", "最近调整"]
    REQUIRED_FIELDS = ["规则编号", "适用格式", "分隔符"]
    STATUS_ORDER = ["草稿", "已生效", "已停用", "被替代"]
    ACTION_RULES = {"启效规则": "已生效", "停用规则": "已停用", "标记被替代": "被替代"}
    NEGATIVE_ACTIONS = ["停用规则"]
