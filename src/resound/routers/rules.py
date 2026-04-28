"""Rules-based router. Reads YAML rules, matches top-down, first match wins.

Predicate DSL (in 'when' clause):
    plain value:    field: "billing"            (exact match)
    operator:       severity: ">=high"          (>= comparison on enum order)
    list:           area: ["billing", "ops"]   (in list)
    range:          confidence: ">0.7"          (numeric comparison)

Supported operators: =, ==, !=, <, <=, >, >=

Severity order: low < medium < high < critical
Sentiment order: negative < neutral < positive (by enum index)
ActionClass order (urgency): ignore < fyi < roadmap < sprint < immediate
"""

from __future__ import annotations

import logging
import re
from typing import Any

from resound.core.router import Router
from resound.models import (
    ActionClass,
    Classification,
    RawSignal,
    Route,
    Sentiment,
    Severity,
)

logger = logging.getLogger(__name__)

# Ordering tables for relational comparisons on enum values.
SEVERITY_ORDER = {s.value: i for i, s in enumerate([Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL])}
SENTIMENT_ORDER = {s.value: i for i, s in enumerate([Sentiment.NEGATIVE, Sentiment.NEUTRAL, Sentiment.POSITIVE, Sentiment.MIXED])}
ACTION_ORDER = {a.value: i for i, a in enumerate([ActionClass.IGNORE, ActionClass.FYI, ActionClass.ROADMAP, ActionClass.SPRINT, ActionClass.IMMEDIATE])}

ORDERINGS: dict[str, dict[str, int]] = {
    "severity": SEVERITY_ORDER,
    "sentiment": SENTIMENT_ORDER,
    "action_class": ACTION_ORDER,
}

OP_RE = re.compile(r"^(>=|<=|==|!=|=|>|<)\s*(.+)$")


class RulesRouter(Router):
    """Routes based on a YAML rules table and a people lookup."""

    def __init__(self, routing_config: dict[str, Any], people_config: dict[str, Any]):
        self.default_route: str = routing_config.get("default_route", "#triage")
        self.rules: list[dict[str, Any]] = routing_config.get("rules", [])
        self.people: dict[str, Any] = people_config or {}

    def route(self, signal: RawSignal, classification: Classification) -> Route:
        # Skip signals the classifier marked ignorable.
        if classification.action_class == ActionClass.IGNORE or not classification.is_about_brand:
            return Route(
                owner_id="(none)",
                destination=None,
                matched_rule="ignored_by_classifier",
                priority="normal",
                notes="Classifier marked this signal as ignore / off-brand.",
            )

        ctx = self._build_context(signal, classification)

        for idx, rule in enumerate(self.rules):
            when = rule.get("when", {})
            if self._match(when, ctx):
                rule_name = rule.get("name", f"rule_{idx}")
                owner = rule.get("route_to", self.default_route)
                priority = rule.get("priority", "normal")
                notes = rule.get("notes")
                destination = self._resolve(owner)
                return Route(
                    owner_id=owner,
                    destination=destination,
                    matched_rule=rule_name,
                    priority=priority,
                    notes=notes,
                )

        # Fallthrough.
        return Route(
            owner_id=self.default_route,
            destination=self._resolve(self.default_route),
            matched_rule="default",
            priority="normal",
        )

    # --- helpers ---

    @staticmethod
    def _build_context(signal: RawSignal, c: Classification) -> dict[str, Any]:
        return {
            "source": signal.source,
            "is_about_brand": c.is_about_brand,
            "area": c.area,
            "subarea": c.subarea or "",
            "sentiment": c.sentiment.value,
            "severity": c.severity.value,
            "action_class": c.action_class.value,
            "confidence": c.confidence,
        }

    def _match(self, when: dict[str, Any], ctx: dict[str, Any]) -> bool:
        for field, expected in when.items():
            actual = ctx.get(field)
            if not self._field_match(field, expected, actual):
                return False
        return True

    @staticmethod
    def _field_match(field: str, expected: Any, actual: Any) -> bool:
        # List: in-set match
        if isinstance(expected, list):
            return actual in expected
        # Bool / numeric: exact
        if isinstance(expected, bool):
            return bool(actual) == expected
        if isinstance(expected, (int, float)) and not isinstance(expected, bool):
            try:
                return float(actual) == float(expected)
            except (TypeError, ValueError):
                return False
        # String: maybe operator
        if isinstance(expected, str):
            m = OP_RE.match(expected)
            if not m:
                return str(actual) == expected
            op, rhs = m.group(1), m.group(2).strip()
            order = ORDERINGS.get(field)
            if order is not None:
                a = order.get(str(actual), -1)
                b = order.get(rhs, -1)
                return _cmp(a, b, op)
            # numeric comparison fallback
            try:
                return _cmp(float(actual), float(rhs), op)
            except (TypeError, ValueError):
                return _cmp(str(actual), str(rhs), op)
        return False

    def _resolve(self, owner_id: str) -> str | None:
        """Resolve @handle or #channel via people.yaml."""
        # people.yaml shape:
        #   people:
        #     "@product-pm": { name: "...", slack: "...", email: "..." }
        #   channels:
        #     "#triage": { slack_channel: "#triage", description: "..." }
        people = self.people.get("people", {})
        channels = self.people.get("channels", {})
        if owner_id in people:
            entry = people[owner_id]
            return entry.get("slack") or entry.get("email") or entry.get("name")
        if owner_id in channels:
            entry = channels[owner_id]
            return entry.get("slack_channel") or entry.get("name")
        return owner_id  # pass-through


def _cmp(a, b, op: str) -> bool:
    if op in ("=", "=="):
        return a == b
    if op == "!=":
        return a != b
    if op == "<":
        return a < b
    if op == "<=":
        return a <= b
    if op == ">":
        return a > b
    if op == ">=":
        return a >= b
    return False
