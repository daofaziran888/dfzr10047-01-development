"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class FieldParseService(BaseModuleService):
    MODULE = "field_parse"
    ENTITY = "解析字段"
    OPERATION_TERM = "解析"
    LIST_FIELDS = ["解析编号", "关联批次", "命中模板", "字段名称", "原始取值", "解析取值", "解析耗时", "解析行号"]
    REQUIRED_FIELDS = ["解析编号", "关联批次", "命中模板"]
    STATUS_ORDER = ["待解析", "解析中", "解析成功", "部分失败"]
    ACTION_RULES = {"启动解析": "解析中", "确认成功": "解析成功", "登记部分失败": "部分失败"}
    NEGATIVE_ACTIONS = []
