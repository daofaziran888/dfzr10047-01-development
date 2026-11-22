"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class ValueCastService(BaseModuleService):
    MODULE = "value_cast"
    ENTITY = "转型规则"
    OPERATION_TERM = "水位"
    LIST_FIELDS = ["转型编号", "目标类型", "来源类型", "日期格式约定", "数值精度", "空值填充", "转型失败数", "最近执行"]
    REQUIRED_FIELDS = ["转型编号", "目标类型", "来源类型"]
    STATUS_ORDER = ["待执行", "执行中", "已完成", "存在失败"]
    ACTION_RULES = {"启动转型": "执行中", "确认完成": "已完成", "登记失败": "存在失败"}
    NEGATIVE_ACTIONS = []
