"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class SchemaSniffService(BaseModuleService):
    MODULE = "schema_sniff"
    ENTITY = "结构推断"
    OPERATION_TERM = "解析"
    LIST_FIELDS = ["嗅探编号", "关联批次", "样本行数", "推断列数", "列名清单", "列类型推断", "首行是否表头", "嗅探置信度"]
    REQUIRED_FIELDS = ["嗅探编号", "关联批次", "样本行数"]
    STATUS_ORDER = ["待嗅探", "已推断", "低置信", "推断冲突"]
    ACTION_RULES = {"执行嗅探": "已推断", "标记低置信": "低置信", "登记冲突": "推断冲突"}
    NEGATIVE_ACTIONS = []
