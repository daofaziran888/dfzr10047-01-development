"""文件投递领域服务：负责异构文件批次的接入登记与接收节点分发，产出投递批次数据集。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class FileIntakeService(BaseModuleService):
    MODULE = "file_intake"
    ENTITY = "投递批次"
    OPERATION_TERM = "解析"
    LIST_FIELDS = ["批次编号", "来源渠道", "原始文件名", "字节大小", "投递时间", "文件后缀", "声明格式", "接收节点"]
    REQUIRED_FIELDS = ["批次编号", "来源渠道", "原始文件名"]
    STATUS_ORDER = ["已接收", "待探测", "探测失败", "已入库"]
    ACTION_RULES = {"发起探测": "待探测", "标记失败": "探测失败", "确认入库": "已入库"}
    NEGATIVE_ACTIONS = []
