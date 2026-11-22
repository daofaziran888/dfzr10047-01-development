"""抽取模板版本管理：过渡期新旧并存→字段差异比对→重解析位点范围。

核心行为：
- 同一格式过渡期内新旧版本并存，两个版本都能命中批次
- 版本生效前必须校验父版本链连续，断链的版本不得启动过渡
- 逐字段比对新旧版本抽取表达式，差异字段数决定重解析的位点范围
- 差异字段数超过偏离上限时禁止一次性重解析全部历史批次
"""
from __future__ import annotations

from typing import Any


class TemplateVersion:
    """单个模板版本。"""

    def __init__(self, template_id: str, name: str, fmt: str, version: str,
                 expressions: dict[str, str], parent_version: str = "",
                 effective_from: str = ""):
        self.template_id = template_id
        self.name = name
        self.fmt = fmt
        self.version = version
        self.expressions = dict(expressions)
        self.parent_version = parent_version
        self.effective_from = effective_from
        self.status = "草稿"
        self.hit_batches: list[str] = []

    @property
    def expression_count(self) -> int:
        return len(self.expressions)

    def to_dict(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id,
            "name": self.name,
            "fmt": self.fmt,
            "version": self.version,
            "expression_count": self.expression_count,
            "parent_version": self.parent_version,
            "effective_from": self.effective_from,
            "status": self.status,
            "hit_count": len(self.hit_batches),
        }


class TemplateDiff:
    """两版模板的差异条目。"""

    def __init__(self, old_version: str, new_version: str, added: list[str],
                 removed: list[str], changed: list[str], affected_batches: int):
        self.old_version = old_version
        self.new_version = new_version
        self.added = added
        self.removed = removed
        self.changed = changed
        self.affected_batches = affected_batches
        self.converged = False

    @property
    def diff_field_count(self) -> int:
        return len(self.added) + len(self.removed) + len(self.changed)

    def field_list(self) -> list[str]:
        return sorted(self.added + self.removed + self.changed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "old_version": self.old_version,
            "new_version": self.new_version,
            "added": self.added,
            "removed": self.removed,
            "changed": self.changed,
            "diff_field_count": self.diff_field_count,
            "affected_batches": self.affected_batches,
            "converged": self.converged,
        }


class ReparseRange:
    """重解析位点范围。"""

    def __init__(self, task_id: str, start_position: str, end_position: str,
                 affected_batches: list[str], split_batches: int):
        self.task_id = task_id
        self.start_position = start_position
        self.end_position = end_position
        self.affected_batches = list(affected_batches)
        self.split_batches = split_batches

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "start_position": self.start_position,
            "end_position": self.end_position,
            "affected_count": len(self.affected_batches),
            "affected_batches": self.affected_batches,
            "split_batches": self.split_batches,
        }


class TemplateVersionManager:
    """抽取模板版本管理器。"""

    MAX_DIFF_FIELDS_SINGLE_PASS = 6

    def __init__(self) -> None:
        self._versions: dict[str, TemplateVersion] = {}
        self._diffs: list[TemplateDiff] = []
        self._ranges: dict[str, ReparseRange] = {}

    def register_version(self, version: TemplateVersion) -> TemplateVersion:
        self._versions[version.template_id] = version
        return version

    def activate_version(self, template_id: str, effective_from: str) -> tuple[bool, str]:
        """生效模板：校验父版本链连续性。"""
        version = self._versions.get(template_id)
        if version is None:
            return False, f"模板 {template_id} 不存在"

        if version.status == "已生效":
            return False, f"模板 {template_id}[{version.version}] 已生效，不能重复生效"

        if version.parent_version:
            parent = self._find_by_version(version.name, version.fmt, version.parent_version)
            if parent is None:
                return False, (
                    f"模板 {template_id} 的父版本 {version.parent_version} 不存在，"
                    f"版本链断裂不得生效"
                )
            if parent.status not in ("已生效", "过渡中", "已废止"):
                return False, (
                    f"父版本 {parent.version} 状态为 {parent.status}，"
                    f"未生效的父版本不能作为过渡起点"
                )

        version.status = "已生效"
        version.effective_from = effective_from
        self._retire_predecessors(version)
        return True, f"模板 {template_id}[{version.version}] 已生效"

    def _retire_predecessors(self, version: TemplateVersion) -> None:
        """同名同格式的更早版本在过渡结束后废止。"""
        for other in self._versions.values():
            if (other.template_id != version.template_id
                    and other.name == version.name
                    and other.fmt == version.fmt
                    and other.status == "过渡中"):
                other.status = "已废止"

    def start_transition(self, template_id: str, effective_from: str) -> tuple[bool, str, list[str]]:
        """启动过渡：新版本进入过渡中，旧版本仍可同时命中。返回并存版本清单。"""
        version = self._versions.get(template_id)
        if version is None:
            return False, f"模板 {template_id} 不存在", []
        if version.status == "已生效":
            return False, f"模板 {template_id}[{version.version}] 已生效无需过渡", []

        version.status = "过渡中"
        version.effective_from = effective_from
        coexisting = self.coexisting_versions(version.name, version.fmt)
        return True, (
            f"模板 {version.name}[{version.fmt}] 进入过渡期，"
            f"并存版本 {coexisting}"
        ), coexisting

    def coexisting_versions(self, name: str, fmt: str) -> list[str]:
        """返回同名同格式下当前并存（过渡中 + 已生效）的版本号。"""
        return sorted(
            v.version for v in self._versions.values()
            if v.name == name and v.fmt == fmt and v.status in ("过渡中", "已生效")
        )

    def resolve_hit_version(self, name: str, fmt: str, batch_time: str) -> str | None:
        """过渡期内选择命中版本：生效时间不晚于批次时间的最新版本。"""
        candidates = [
            v for v in self._versions.values()
            if v.name == name and v.fmt == fmt and v.status in ("过渡中", "已生效")
        ]
        if not candidates:
            return None
        eligible = [v for v in candidates if v.effective_from and v.effective_from <= batch_time]
        pool = eligible or candidates
        return max(pool, key=lambda v: (v.effective_from or "", v.version)).template_id

    def record_hit(self, template_id: str, batch_id: str) -> None:
        version = self._versions.get(template_id)
        if version is not None and batch_id not in version.hit_batches:
            version.hit_batches.append(batch_id)

    def _find_by_version(self, name: str, fmt: str, version_no: str) -> TemplateVersion | None:
        for v in self._versions.values():
            if v.name == name and v.fmt == fmt and v.version == version_no:
                return v
        return None

    def diff_versions(self, old_template_id: str, new_template_id: str,
                      affected_batches: int) -> TemplateDiff | None:
        """逐字段比对两版抽取表达式。"""
        old = self._versions.get(old_template_id)
        new = self._versions.get(new_template_id)
        if old is None or new is None:
            return None

        old_keys = set(old.expressions)
        new_keys = set(new.expressions)
        added = sorted(new_keys - old_keys)
        removed = sorted(old_keys - new_keys)
        changed = sorted(
            k for k in (old_keys & new_keys)
            if old.expressions[k] != new.expressions[k]
        )

        diff = TemplateDiff(old.version, new.version, added, removed, changed, affected_batches)
        diff.converged = diff.diff_field_count <= self.MAX_DIFF_FIELDS_SINGLE_PASS
        self._diffs.append(diff)
        return diff

    def plan_reparse_range(self, task_id: str, diff: TemplateDiff,
                           batch_positions: dict[str, str]) -> tuple[bool, str, ReparseRange | None]:
        """按差异条目规划重解析位点范围。

        batch_positions: 受影响批次编号 → 位点（时间戳或序号字符串，可排序）。
        差异字段数超过单趟上限时强制分批，返回的分批数大于 1。
        """
        if not batch_positions:
            return False, f"差异 {diff.old_version}→{diff.new_version} 没有受影响批次，无需重解析", None

        ordered = sorted(batch_positions.items(), key=lambda kv: kv[1])
        start_position = ordered[0][1]
        end_position = ordered[-1][1]
        affected = [b for b, _ in ordered]

        split_batches = 1
        if diff.diff_field_count > self.MAX_DIFF_FIELDS_SINGLE_PASS:
            split_batches = -(-diff.diff_field_count // self.MAX_DIFF_FIELDS_SINGLE_PASS)

        rng = ReparseRange(task_id, start_position, end_position, affected, split_batches)
        self._ranges[task_id] = rng
        note = f"，需分 {split_batches} 批执行" if split_batches > 1 else ""
        return True, (
            f"重解析范围 [{start_position}, {end_position}] 覆盖 {len(affected)} 个批次{note}"
        ), rng

    def get_range(self, task_id: str) -> ReparseRange | None:
        return self._ranges.get(task_id)

    def get_diffs(self) -> list[TemplateDiff]:
        return list(self._diffs)

    def get_version(self, template_id: str) -> TemplateVersion | None:
        return self._versions.get(template_id)

    def snapshot(self) -> dict[str, Any]:
        return {
            "versions": {k: v.to_dict() for k, v in self._versions.items()},
            "diffs": [d.to_dict() for d in self._diffs],
            "reparse_ranges": {k: v.to_dict() for k, v in self._ranges.items()},
        }
