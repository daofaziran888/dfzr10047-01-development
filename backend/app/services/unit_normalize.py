"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class UnitNormalizeService(BaseModuleService):
    MODULE = "unit_normalize"
    ENTITY = "归一系数"
    OPERATION_TERM = "校验"
    LIST_FIELDS = ["归一编号", "字段名称", "原始单位", "目标单位", "换算系数", "适用来源", "生效起日", "最近命中"]
    REQUIRED_FIELDS = ["归一编号", "字段名称", "原始单位"]
    STATUS_ORDER = ["草稿", "已生效", "已停用", "系数冲突"]
    ACTION_RULES = {"启效系数": "已生效", "停用系数": "已停用", "登记冲突": "系数冲突"}
    NEGATIVE_ACTIONS = ["停用系数"]
