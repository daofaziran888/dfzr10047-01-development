"""解析器路由：首选解析器失败→按备选顺序回退→回退计数供指标结算。

核心行为：
- 按探测认定的真实格式选择首选解析器，声明格式与真实格式不一致时以真实格式为准
- 首选解析器失败按备选清单顺序回退，回退次数逐次累加
- 备选清单耗尽仍失败时判定路由失败，该批次不进入字段解析
"""
from __future__ import annotations

from typing import Any


class RouteDecision:
    """单次路由决策。"""

    def __init__(self, decision_id: str, batch_id: str, resolved_format: str,
                 primary_parser: str, fallback_parsers: list[str], basis: str):
        self.decision_id = decision_id
        self.batch_id = batch_id
        self.resolved_format = resolved_format
        self.primary_parser = primary_parser
        self.fallback_parsers = list(fallback_parsers)
        self.basis = basis
        self.selected_parser = ""
        self.fallback_count = 0
        self.status = "待路由"
        self.decide_time = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "batch_id": self.batch_id,
            "resolved_format": self.resolved_format,
            "primary_parser": self.primary_parser,
            "fallback_parsers": self.fallback_parsers,
            "selected_parser": self.selected_parser,
            "fallback_count": self.fallback_count,
            "status": self.status,
            "basis": self.basis,
            "decide_time": self.decide_time,
        }


class ParserRouteEngine:
    """解析器路由引擎。"""

    def __init__(self) -> None:
        self._format_parsers: dict[str, list[str]] = {}
        self._decisions: dict[str, RouteDecision] = {}

    def register_parsers(self, fmt: str, parsers: list[str]) -> None:
        """注册格式的解析器优先级清单：首个为首选，其余为备选。"""
        self._format_parsers[fmt] = list(parsers)

    def route(self, decision_id: str, batch_id: str, resolved_format: str,
              basis: str, decide_time: str) -> tuple[bool, RouteDecision | None]:
        """按认定格式选定首选解析器。"""
        parsers = self._format_parsers.get(resolved_format, [])
        if not parsers:
            decision = RouteDecision(decision_id, batch_id, resolved_format,
                                     "", [], basis)
            decision.status = "路由失败"
            decision.decide_time = decide_time
            self._decisions[decision_id] = decision
            return False, decision

        decision = RouteDecision(decision_id, batch_id, resolved_format,
                                 parsers[0], parsers[1:], basis)
        decision.selected_parser = parsers[0]
        decision.status = "已选定"
        decision.decide_time = decide_time
        self._decisions[decision_id] = decision
        return True, decision

    def execute_with_fallback(self, decision_id: str,
                              try_parse: Any,
                              fail_time: str) -> tuple[bool, str, RouteDecision | None]:
        """执行首选解析器，失败时按备选顺序回退。

        try_parse(parser_id) -> bool 由调用方提供真实解析成败判定。
        """
        decision = self._decisions.get(decision_id)
        if decision is None:
            return False, f"路由决策 {decision_id} 不存在", None

        if decision.status == "路由失败":
            return False, (
                f"批次 {decision.batch_id} 格式 {decision.resolved_format} "
                f"无可用解析器，路由失败"
            ), decision

        candidates = [decision.primary_parser] + decision.fallback_parsers
        for index, parser in enumerate(candidates):
            if try_parse(parser):
                decision.selected_parser = parser
                decision.fallback_count = index
                decision.status = "已回退" if index > 0 else "已选定"
                decision.decide_time = fail_time
                if index > 0:
                    return True, (
                        f"首选解析器 {decision.primary_parser} 失败，"
                        f"回退到 {parser} 成功（回退 {index} 次）"
                    ), decision
                return True, f"首选解析器 {parser} 命中，无需回退", decision

        decision.fallback_count = len(decision.fallback_parsers) + 1
        decision.status = "路由失败"
        decision.decide_time = fail_time
        return False, (
            f"批次 {decision.batch_id} 全部 {len(candidates)} 个解析器均失败，判定路由失败"
        ), decision

    def fallback_stats(self) -> tuple[int, int]:
        """返回 (发生回退的决策数, 决策总数)，供回退率结算。"""
        decisions = list(self._decisions.values())
        fallbacks = sum(1 for d in decisions if d.fallback_count > 0)
        return fallbacks, len(decisions)

    def get_decision(self, decision_id: str) -> RouteDecision | None:
        return self._decisions.get(decision_id)

    def decisions_of_batch(self, batch_id: str) -> list[RouteDecision]:
        return [d for d in self._decisions.values() if d.batch_id == batch_id]

    def snapshot(self) -> dict[str, Any]:
        fallbacks, total = self.fallback_stats()
        return {
            "format_parsers": dict(self._format_parsers),
            "decisions": {k: v.to_dict() for k, v in self._decisions.items()},
            "fallback_count": fallbacks,
            "decision_total": total,
        }
