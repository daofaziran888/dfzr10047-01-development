"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class RowQuarantineService(BaseModuleService):
    MODULE = "row_quarantine"
    ENTITY = "隔离行"
    OPERATION_TERM = "解析"
    LIST_FIELDS = ["隔离编号", "关联批次", "原始行号", "失败字段", "失败原因", "原始行文本", "复核结论", "隔离时间"]
    REQUIRED_FIELDS = ["隔离编号", "关联批次", "原始行号"]
    STATUS_ORDER = ["已隔离", "复核中", "已回补", "已废弃"]
    ACTION_RULES = {"提交复核": "复核中", "回补批次": "已回补", "废弃隔离行": "已废弃"}
    NEGATIVE_ACTIONS = []
