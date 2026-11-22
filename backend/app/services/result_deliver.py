"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class ResultDeliverService(BaseModuleService):
    MODULE = "result_deliver"
    ENTITY = "投递记录"
    OPERATION_TERM = "解析"
    LIST_FIELDS = ["投递记录编号", "关联契约", "目标位置", "投递行数", "投递格式", "重试次数", "投递结论", "投递时间"]
    REQUIRED_FIELDS = ["投递记录编号", "关联契约", "目标位置"]
    STATUS_ORDER = ["待投递", "投递中", "已送达", "部分送达"]
    ACTION_RULES = {"启动投递": "投递中", "确认送达": "已送达", "登记部分送达": "部分送达"}
    NEGATIVE_ACTIONS = []
