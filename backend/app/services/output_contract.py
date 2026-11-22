"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class OutputContractService(BaseModuleService):
    MODULE = "output_contract"
    ENTITY = "契约条目"
    OPERATION_TERM = "解析"
    LIST_FIELDS = ["契约编号", "关联批次", "输出列集合", "列顺序约定", "必填列", "行数下限", "契约校验结论", "校验时间"]
    REQUIRED_FIELDS = ["契约编号", "关联批次", "输出列集合"]
    STATUS_ORDER = ["待校验", "校验中", "已通过", "未通过"]
    ACTION_RULES = {"启动校验": "校验中", "确认通过": "已通过", "登记未通过": "未通过"}
    NEGATIVE_ACTIONS = []
