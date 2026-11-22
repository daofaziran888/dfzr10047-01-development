"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class ReparseTaskService(BaseModuleService):
    MODULE = "reparse_task"
    ENTITY = "重解析单"
    OPERATION_TERM = "解析"
    LIST_FIELDS = ["重解析编号", "关联批次", "重解析原因", "覆盖策略", "起始位点", "截止位点", "受影响投递数", "重解析结论"]
    REQUIRED_FIELDS = ["重解析编号", "关联批次", "重解析原因"]
    STATUS_ORDER = ["待执行", "执行中", "已完成", "被中止"]
    ACTION_RULES = {"启动重解析": "执行中", "确认完成": "已完成", "中止任务": "被中止"}
    NEGATIVE_ACTIONS = []
