"""结构嗅探与分隔规则引擎：抽样推断列结构→首行表头判定→切分规则选择。

核心行为：
- 对样本行按分隔规则试切分，推断列数与列类型
- 首行是否表头的结论直接改变字段解析的起始行（1 或 2）
- 同一段文本在不同分隔规则下会切出不同列数，规则切换时置信度下降
"""
from __future__ import annotations

import csv
import io
from typing import Any


class DelimiterRule:
    """分隔规则条目。"""

    def __init__(self, rule_id: str, fmt: str, delimiter: str,
                 quotechar: str, escapechar: str):
        self.rule_id = rule_id
        self.fmt = fmt
        self.delimiter = delimiter
        self.quotechar = quotechar
        self.escapechar = escapechar
        self.hit_batches: list[str] = []

    def split_line(self, line: str) -> list[str]:
        """按规则切分一行。"""
        reader = csv.reader(
            io.StringIO(line), delimiter=self.delimiter,
            quotechar=self.quotechar, escapechar=self.escapechar,
        )
        for row in reader:
            return row
        return []

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "fmt": self.fmt,
            "delimiter": self.delimiter,
            "quotechar": self.quotechar,
            "escapechar": self.escapechar,
            "hit_count": len(self.hit_batches),
        }


class SniffResult:
    """结构推断结果。"""

    def __init__(self, batch_id: str, sample_rows: int, column_count: int,
                 column_names: list[str], column_types: list[str],
                 first_row_is_header: bool, confidence: float,
                 parse_start_row: int):
        self.batch_id = batch_id
        self.sample_rows = sample_rows
        self.column_count = column_count
        self.column_names = column_names
        self.column_types = column_types
        self.first_row_is_header = first_row_is_header
        self.confidence = confidence
        self.parse_start_row = parse_start_row

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "sample_rows": self.sample_rows,
            "column_count": self.column_count,
            "column_names": self.column_names,
            "column_types": self.column_types,
            "first_row_is_header": self.first_row_is_header,
            "confidence": self.confidence,
            "parse_start_row": self.parse_start_row,
        }


class StructureSniffer:
    """结构嗅探器：管理分隔规则并执行列结构推断。"""

    LOW_CONFIDENCE = 0.60

    def __init__(self) -> None:
        self._rules: dict[str, DelimiterRule] = {}
        self._sniffs: dict[str, SniffResult] = {}

    def register_rule(self, rule: DelimiterRule) -> None:
        self._rules[rule.rule_id] = rule

    def get_active_rule(self, fmt: str) -> DelimiterRule | None:
        """获取指定格式的第一个注册规则（按注册顺序）。"""
        for rule in self._rules.values():
            if rule.fmt == fmt:
                return rule
        return None

    def replace_rule(self, fmt: str, new_rule: DelimiterRule) -> DelimiterRule | None:
        """替换指定格式的生效规则，返回被替代的旧规则。

        同格式只保留一条生效规则：命中旧规则的批次清单迁移到新规则上，
        旧规则本身被移出注册表（在分隔规则服务里体现为「被替代」状态）。
        """
        old: DelimiterRule | None = None
        for rule_id in list(self._rules):
            rule = self._rules[rule_id]
            if rule.fmt == fmt:
                if old is None:
                    old = rule
                del self._rules[rule_id]
        if old is not None:
            new_rule.hit_batches = list(old.hit_batches)
        self._rules[new_rule.rule_id] = new_rule
        return old

    def _guess_type(self, values: list[str]) -> str:
        """按样本值推断列类型。"""
        non_empty = [v.strip() for v in values if v.strip()]
        if not non_empty:
            return "str"
        all_int = True
        all_num = True
        all_date = True
        for v in non_empty:
            try:
                int(v)
            except ValueError:
                all_int = False
            try:
                float(v)
            except ValueError:
                all_num = False
            parts = v.replace("T", " ").split(" ")
            if not (len(parts[0].split("-")) == 3 or len(parts) == 2):
                all_date = False
        if all_int:
            return "int"
        if all_num:
            return "float"
        if all_date:
            return "datetime"
        return "str"

    def sniff(self, batch_id: str, fmt: str, sample_lines: list[str]) -> tuple[bool, SniffResult]:
        """对样本行执行结构嗅探。返回 (是否可用, 推断结果)。"""
        rule = self.get_active_rule(fmt)
        if rule is None:
            result = SniffResult(batch_id, len(sample_lines), 0, [], [], False, 0.0, 1)
            self._sniffs[batch_id] = result
            return False, result

        rule.hit_batches.append(batch_id)
        split_rows = [rule.split_line(line) for line in sample_lines if line.strip()]
        if not split_rows:
            result = SniffResult(batch_id, 0, 0, [], [], False, 0.0, 1)
            self._sniffs[batch_id] = result
            return False, result

        counts = [len(r) for r in split_rows]
        column_count = counts[0]
        consistent = sum(1 for c in counts if c == column_count)
        consistency = consistent / len(counts)

        first_row_is_header = False
        if consistency >= 0.8 and len(split_rows) >= 2:
            first = split_rows[0]
            rest = split_rows[1:]
            first_is_alpha = all(
                v.strip() and not v.strip().replace(".", "").replace("-", "").isdigit()
                for v in first if v.strip()
            )
            rest_types_stable = all(
                self._guess_type([r[i] for r in rest if i < len(r)]) in ("int", "float", "datetime")
                for i in range(min(column_count, 4))
            ) if column_count else False
            first_row_is_header = bool(first_is_alpha and (rest_types_stable or column_count <= 2))

        data_rows = split_rows[1:] if first_row_is_header else split_rows
        column_names = (
            [c.strip() for c in split_rows[0]] if first_row_is_header
            else [f"col-{i}" for i in range(column_count)]
        )
        column_types = [
            self._guess_type([r[i] for r in data_rows if i < len(r)])
            for i in range(column_count)
        ]

        confidence = round(
            consistency * (0.95 if first_row_is_header or column_count <= 8 else 0.7), 2
        )
        parse_start_row = 2 if first_row_is_header else 1

        result = SniffResult(
            batch_id, len(split_rows), column_count, column_names,
            column_types, first_row_is_header, confidence, parse_start_row,
        )
        self._sniffs[batch_id] = result
        return confidence >= self.LOW_CONFIDENCE, result

    def get_sniff(self, batch_id: str) -> SniffResult | None:
        return self._sniffs.get(batch_id)

    def parse_start_row(self, batch_id: str) -> int:
        """字段解析消费的起始行结论。"""
        result = self._sniffs.get(batch_id)
        return result.parse_start_row if result else 1

    def snapshot(self) -> dict[str, Any]:
        return {
            "rules": {k: v.to_dict() for k, v in self._rules.items()},
            "sniffs": {k: v.to_dict() for k, v in self._sniffs.items()},
        }
