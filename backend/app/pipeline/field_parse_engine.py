"""字段解析引擎：模板命中→逐字段抽取→解析质量记录。

核心行为：
- 根据解析路由选定的解析器与命中模板逐字段抽取取值
- 原始取值无法解析时记录失败信息供坏行隔离消费
- 成功字段供后续取值转型与输出契约使用
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any


class ParseFieldResult:
    """单字段解析结果。"""

    def __init__(self, field_name: str, raw_value: str, parsed_value: Any,
                 success: bool, error_reason: str = "", row_num: int = 0):
        self.field_name = field_name
        self.raw_value = raw_value
        self.parsed_value = parsed_value
        self.success = success
        self.error_reason = error_reason
        self.row_num = row_num

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_name": self.field_name,
            "raw_value": self.raw_value,
            "parsed_value": str(self.parsed_value) if self.parsed_value is not None else "",
            "success": self.success,
            "error_reason": self.error_reason,
            "row_num": self.row_num,
        }


class ParseRowResult:
    """单行解析结果摘要。"""

    def __init__(self, row_num: int, batch_id: str, template_id: str,
                 fields: list[ParseFieldResult]):
        self.row_num = row_num
        self.batch_id = batch_id
        self.template_id = template_id
        self.fields = fields
        self.success_count = sum(1 for f in fields if f.success)
        self.failure_count = sum(1 for f in fields if not f.success)

    @property
    def all_success(self) -> bool:
        return self.failure_count == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "row_num": self.row_num,
            "template_id": self.template_id,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "fields": [f.to_dict() for f in self.fields],
        }


class FieldParseEngine:
    """字段解析引擎：管理模板、执行逐字段抽取、汇总解析质量。"""

    def __init__(self) -> None:
        self._templates: dict[str, dict[str, Any]] = {}
        self._parse_results: dict[str, list[ParseRowResult]] = {}

    def register_template(self, template_id: str, field_defs: list[dict[str, Any]]) -> None:
        """注册字段抽取模板：字段名→类型→解析规则。"""
        self._templates[template_id] = {
            "field_defs": field_defs,
        }

    def parse_row(self, batch_id: str, template_id: str, row_num: int,
                  raw_values: dict[str, str]) -> ParseRowResult:
        """逐字段解析单行数据。"""
        template = self._templates.get(template_id)
        if template is None:
            results = [
                ParseFieldResult(k, v, None, False, f"模板 {template_id} 不存在", row_num)
                for k, v in raw_values.items()
            ]
            pr = ParseRowResult(row_num, batch_id, template_id, results)
            self._store_result(batch_id, pr)
            return pr

        field_defs = template["field_defs"]
        field_def_map = {fd["name"]: fd for fd in field_defs}
        results: list[ParseFieldResult] = []

        for field_name, raw_value in raw_values.items():
            fd = field_def_map.get(field_name)
            if fd is None:
                results.append(ParseFieldResult(
                    field_name, raw_value, raw_value, True, "", row_num,
                ))
                continue
            success, parsed, err = self._cast_value(field_name, raw_value, fd)
            results.append(ParseFieldResult(
                field_name, raw_value, parsed, success, err, row_num,
            ))

        pr = ParseRowResult(row_num, batch_id, template_id, results)
        self._store_result(batch_id, pr)
        return pr

    def _cast_value(self, field_name: str, raw_value: str,
                    field_def: dict[str, Any]) -> tuple[bool, Any, str]:
        """类型转换：str→target_type。"""
        target_type = field_def.get("type", "str")
        if not raw_value or raw_value.strip() == "":
            if field_def.get("nullable", True):
                return True, None, ""
            return False, None, f"字段 {field_name} 不可为空"

        try:
            if target_type in ("str", "string", "text"):
                return True, raw_value.strip(), ""
            elif target_type in ("int", "int64", "integer"):
                return True, int(raw_value.strip()), ""
            elif target_type in ("float", "float64", "double"):
                return True, float(raw_value.strip()), ""
            elif target_type in ("datetime", "datetime64"):
                dt = datetime.fromisoformat(raw_value.strip().replace(" ", "T"))
                return True, dt.isoformat(), ""
            elif target_type == "date":
                date.fromisoformat(raw_value.strip())
                return True, raw_value.strip(), ""
            elif target_type == "bool":
                lower = raw_value.strip().lower()
                if lower in ("true", "1", "yes"):
                    return True, True, ""
                if lower in ("false", "0", "no", ""):
                    return True, False, ""
                return False, None, f"字段 {field_name} 无法解析为布尔值: {raw_value}"
            elif target_type == "category":
                valid = field_def.get("valid_values", [])
                if not valid or raw_value.strip() in valid:
                    return True, raw_value.strip(), ""
                return False, None, f"字段 {field_name} 取值 {raw_value} 不在允许值 {valid} 中"
            else:
                return True, raw_value.strip(), ""
        except (ValueError, TypeError) as e:
            return False, None, f"字段 {field_name} 转型 {target_type} 失败: {e}"

    def _store_result(self, batch_id: str, result: ParseRowResult) -> None:
        self._parse_results.setdefault(batch_id, []).append(result)

    def get_batch_results(self, batch_id: str) -> list[ParseRowResult]:
        return self._parse_results.get(batch_id, [])

    def get_failed_fields(self, batch_id: str) -> list[ParseFieldResult]:
        """获取指定批次所有解析失败字段（供坏行隔离消费）。"""
        failed: list[ParseFieldResult] = []
        for pr in self.get_batch_results(batch_id):
            failed.extend(f for f in pr.fields if not f.success)
        return failed

    def batch_quality_summary(self, batch_id: str) -> dict[str, Any]:
        """解析质量汇总：总行数、成功行数、失败行数、逐行摘要。"""
        results = self.get_batch_results(batch_id)
        total_rows = len(results)
        success_rows = sum(1 for r in results if r.all_success)
        failed_rows = total_rows - success_rows
        total_fields = sum(r.success_count + r.failure_count for r in results)
        failed_fields = sum(r.failure_count for r in results)
        return {
            "batch_id": batch_id,
            "total_rows": total_rows,
            "success_rows": success_rows,
            "failed_rows": failed_rows,
            "total_fields": total_fields,
            "failed_fields": failed_fields,
            "failure_rate": failed_fields / total_fields if total_fields > 0 else 0.0,
        }

    def snapshot(self) -> dict[str, Any]:
        return {
            "templates": list(self._templates.keys()),
            "batches": {
                k: self.batch_quality_summary(k)
                for k in self._parse_results
            },
        }