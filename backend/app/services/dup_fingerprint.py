"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class DupFingerprintService(BaseModuleService):
    MODULE = "dup_fingerprint"
    ENTITY = "指纹记录"
    OPERATION_TERM = "关联"
    LIST_FIELDS = ["指纹编号", "关联批次", "内容指纹", "结构指纹", "命中重复批次", "重复判定", "去重处置", "判定时间"]
    REQUIRED_FIELDS = ["指纹编号", "关联批次", "内容指纹"]
    STATUS_ORDER = ["已计算", "疑似重复", "确认重复", "判定唯一"]
    ACTION_RULES = {"计算指纹": "疑似重复", "确认重复": "确认重复", "判定唯一": "判定唯一"}
    NEGATIVE_ACTIONS = []
