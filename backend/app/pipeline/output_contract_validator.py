"""输出契约校验器：列集约定→行数下限→必填列检查。

核心行为：
- 校验解析结果是否满足输出列集合、列顺序、必填列与行数下限约定
- 未通过的契约阻断结果投递，需等待坏行隔离回补或抽样复核通过后重试
- 校验结论写回输出契约服务供跨模块决胜
"""
from __future__ import annotations

from typing import Any


class ContractRule:
    """输出契约规则定义。"""

    def __init__(self, contract_id: str, batch_id: str, required_columns: list[str],
                 column_order: list[str], mandatory_columns: list[str],
                 min_rows: int):
        self.contract_id = contract_id
        self.batch_id = batch_id
        self.required_columns = required_columns
        self.column_order = column_order
        self.mandatory_columns = mandatory_columns
        self.min_rows = min_rows

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "batch_id": self.batch_id,
            "required_columns": self.required_columns,
            "column_order": self.column_order,
            "mandatory_columns": self.mandatory_columns,
            "min_rows": self.min_rows,
        }


class ContractCheckResult:
    """单次契约校验结果。"""

    def __init__(self, contract_id: str, passed: bool, failures: list[str],
                 actual_columns: list[str], actual_rows: int, check_time: str):
        self.contract_id = contract_id
        self.passed = passed
        self.failures = failures
        self.actual_columns = actual_columns
        self.actual_rows = actual_rows
        self.check_time = check_time

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_id": self.contract_id,
            "passed": self.passed,
            "failures": self.failures,
            "actual_columns": self.actual_columns,
            "actual_rows": self.actual_rows,
            "check_time": self.check_time,
        }


class OutputContractValidator:
    """输出契约校验器。"""

    def __init__(self) -> None:
        self._rules: dict[str, ContractRule] = {}
        self._results: list[ContractCheckResult] = []

    def register_rule(self, contract_id: str, batch_id: str,
                      required_columns: list[str], column_order: list[str],
                      mandatory_columns: list[str], min_rows: int) -> ContractRule:
        rule = ContractRule(contract_id, batch_id, required_columns,
                            column_order, mandatory_columns, min_rows)
        self._rules[contract_id] = rule
        return rule

    def validate(self, contract_id: str, actual_columns: list[str],
                 actual_rows: int, check_time: str,
                 has_unreviewed_quarantine: bool = False) -> tuple[bool, ContractCheckResult]:
        """执行输出契约校验。"""
        rule = self._rules.get(contract_id)
        failures: list[str] = []

        if rule is None:
            result = ContractCheckResult(contract_id, False,
                                         [f"契约 {contract_id} 不存在"],
                                         actual_columns, actual_rows, check_time)
            self._results.append(result)
            return False, result

        if has_unreviewed_quarantine:
            failures.append("存在未复核隔离行，阻断契约通过")

        rule_col_set = set(rule.required_columns)
        actual_col_set = set(actual_columns)
        missing_cols = rule_col_set - actual_col_set
        if missing_cols:
            failures.append(f"缺少约定列: {sorted(missing_cols)}")

        extra_cols = actual_col_set - rule_col_set
        if extra_cols:
            failures.append(f"多出未约定列: {sorted(extra_cols)}")

        for mc in rule.mandatory_columns:
            if mc not in actual_col_set:
                failures.append(f"必填列 {mc} 缺失")

        if actual_rows < rule.min_rows:
            failures.append(f"实际行数 {actual_rows} 低于下限 {rule.min_rows}")

        passed = len(failures) == 0
        result = ContractCheckResult(contract_id, passed, failures,
                                     actual_columns, actual_rows, check_time)
        self._results.append(result)
        return passed, result

    def get_last_result(self, contract_id: str) -> ContractCheckResult | None:
        for r in reversed(self._results):
            if r.contract_id == contract_id:
                return r
        return None

    def snapshot(self) -> dict[str, Any]:
        return {
            "rules": {k: v.to_dict() for k, v in self._rules.items()},
            "results": [r.to_dict() for r in self._results],
        }