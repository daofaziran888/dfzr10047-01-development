"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class ParserRouteService(BaseModuleService):
    MODULE = "parser_route"
    ENTITY = "路由决策"
    OPERATION_TERM = "解析"
    LIST_FIELDS = ["决策编号", "关联批次", "推断格式", "命中解析器", "备选解析器", "路由依据", "回退次数", "决策时间"]
    REQUIRED_FIELDS = ["决策编号", "关联批次", "推断格式"]
    STATUS_ORDER = ["待路由", "已选定", "已回退", "路由失败"]
    ACTION_RULES = {"选定解析器": "已选定", "执行回退": "已回退", "判定失败": "路由失败"}
    NEGATIVE_ACTIONS = []
