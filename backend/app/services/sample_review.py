"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class SampleReviewService(BaseModuleService):
    MODULE = "sample_review"
    ENTITY = "复核样本"
    OPERATION_TERM = "解析"
    LIST_FIELDS = ["样本编号", "关联批次", "抽样比例", "抽样行数", "字段一致数", "取值偏差数", "复核结论", "复核人标识"]
    REQUIRED_FIELDS = ["样本编号", "关联批次", "抽样比例"]
    STATUS_ORDER = ["待复核", "复核中", "已通过", "已驳回"]
    ACTION_RULES = {"启动复核": "复核中", "通过样本": "已通过", "驳回样本": "已驳回"}
    NEGATIVE_ACTIONS = ["驳回样本"]
