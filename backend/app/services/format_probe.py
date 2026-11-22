"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class FormatProbeService(BaseModuleService):
    MODULE = "format_probe"
    ENTITY = "探测结论"
    OPERATION_TERM = "读取"
    LIST_FIELDS = ["探测编号", "关联批次", "魔数特征", "推断格式", "置信度", "结构层级", "是否压缩", "探测耗时"]
    REQUIRED_FIELDS = ["探测编号", "关联批次", "魔数特征"]
    STATUS_ORDER = ["待探测", "已确认", "存疑", "无法识别"]
    ACTION_RULES = {"确认格式": "已确认", "标记存疑": "存疑", "判定无法识别": "无法识别"}
    NEGATIVE_ACTIONS = []
