"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class NestedFlattenService(BaseModuleService):
    MODULE = "nested_flatten"
    ENTITY = "展平路径"
    OPERATION_TERM = "关联"
    LIST_FIELDS = ["展平编号", "关联模板", "原始路径", "展平后列名", "数组处理方式", "最大展开层数", "空节点处置", "展平行数"]
    REQUIRED_FIELDS = ["展平编号", "关联模板", "原始路径"]
    STATUS_ORDER = ["待展平", "已展平", "层数超限", "空节点过多"]
    ACTION_RULES = {"执行展平": "已展平", "登记超限": "层数超限", "标记空节点过多": "空节点过多"}
    NEGATIVE_ACTIONS = []
