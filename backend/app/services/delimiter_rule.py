"""分隔规则领域服务：维护各格式的切分转义约定与规则版本，产出规则条目数据集。"""
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
