"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class EncodingNormService(BaseModuleService):
    MODULE = "encoding_norm"
    ENTITY = "转码记录"
    OPERATION_TERM = "读取"
    LIST_FIELDS = ["转码编号", "关联批次", "原始编码", "目标编码", "不可映射字符数", "替换策略", "转码后字节", "转码耗时"]
    REQUIRED_FIELDS = ["转码编号", "关联批次", "原始编码"]
    STATUS_ORDER = ["待转码", "转码中", "已完成", "存在损字"]
    ACTION_RULES = {"启动转码": "转码中", "确认完成": "已完成", "登记损字": "存在损字"}
    NEGATIVE_ACTIONS = []
