"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class ExtractTmplService(BaseModuleService):
    MODULE = "extract_tmpl"
    ENTITY = "模板版本"
    OPERATION_TERM = "解析"
    LIST_FIELDS = ["模板编号", "模板名称", "适用格式", "版本号", "抽取表达式数", "父版本号", "生效时间", "最近命中"]
    REQUIRED_FIELDS = ["模板编号", "模板名称", "适用格式"]
    STATUS_ORDER = ["草稿", "过渡中", "已生效", "已废止"]
    ACTION_RULES = {"启动过渡": "过渡中", "生效模板": "已生效", "废止模板": "已废止"}
    NEGATIVE_ACTIONS = []
