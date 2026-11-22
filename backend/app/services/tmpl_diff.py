"""__NAME__领域服务：字段、状态和动作来自业务配置，数据处理骨架由基类复用。"""
from __future__ import annotations

from app.services.base import BaseModuleService


class TmplDiffService(BaseModuleService):
    MODULE = "tmpl_diff"
    ENTITY = "差异条目"
    OPERATION_TERM = "解析"
    LIST_FIELDS = ["差异编号", "旧模板版本", "新模板版本", "差异字段", "差异类别", "影响批次数", "修正方案", "登记时间"]
    REQUIRED_FIELDS = ["差异编号", "旧模板版本", "新模板版本"]
    STATUS_ORDER = ["待比对", "比对中", "已收敛", "偏离超限"]
    ACTION_RULES = {"启动比对": "比对中", "确认收敛": "已收敛", "标记超限": "偏离超限"}
    NEGATIVE_ACTIONS = []
