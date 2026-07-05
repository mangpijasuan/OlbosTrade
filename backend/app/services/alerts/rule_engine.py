"""
Smart Alerts rule engine — pure, deterministic condition evaluation + mode
routing.

A rule is a set of predicates combined with AND over a metrics snapshot. When
all predicates pass, the rule fires; how the fire is handled depends on the
trading mode:

  * manual    -> informational notification only
  * copilot   -> a review CARD (requires human approval; still gated downstream)
  * autopilot -> a CANDIDATE only, which must pass every existing system gate

Critical invariant: `route_outcome` never returns anything that submits an
order. It returns a typed intent (notify / review / candidate). Order placement
lives entirely in the execution path and is not importable here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Op = Literal["gt", "gte", "lt", "lte", "eq", "ne", "contains", "is_true", "is_false", "within"]
Mode = Literal["manual", "copilot", "autopilot"]
OutcomeKind = Literal["notify", "review_card", "candidate"]


@dataclass
class Predicate:
    metric: str
    op: Op
    value: Any = None

    def evaluate(self, snapshot: dict) -> bool:
        if self.metric not in snapshot:
            return False                     # missing metric never satisfies a rule
        actual = snapshot[self.metric]
        if actual is None:
            return False
        try:
            if self.op == "gt":      return actual > self.value
            if self.op == "gte":     return actual >= self.value
            if self.op == "lt":      return actual < self.value
            if self.op == "lte":     return actual <= self.value
            if self.op == "eq":      return actual == self.value
            if self.op == "ne":      return actual != self.value
            if self.op == "contains": return str(self.value).lower() in str(actual).lower()
            if self.op == "is_true":  return bool(actual) is True
            if self.op == "is_false": return bool(actual) is False
            if self.op == "within":   return actual <= self.value   # e.g. minutes-to-event <= X
        except TypeError:
            return False
        return False


@dataclass
class Rule:
    rule_id: str
    name: str
    symbol: str
    predicates: list[Predicate]
    mode: Mode = "manual"
    enabled: bool = True

    def matches(self, snapshot: dict) -> bool:
        """All predicates must pass (AND). An empty rule never fires."""
        if not self.enabled or not self.predicates:
            return False
        return all(p.evaluate(snapshot) for p in self.predicates)


@dataclass
class AlertOutcome:
    rule_id: str
    symbol: str
    kind: OutcomeKind
    mode: Mode
    message: str
    evidence: list[str] = field(default_factory=list)
    # NEVER an order — an autopilot outcome is a candidate that must still pass
    # every downstream gate. This flag documents the safety contract explicitly.
    requires_full_gate_check: bool = False

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id, "symbol": self.symbol, "kind": self.kind,
            "mode": self.mode, "message": self.message, "evidence": self.evidence,
            "requires_full_gate_check": self.requires_full_gate_check,
            "creates_order": False,          # invariant, surfaced for auditability
        }


def route_outcome(rule: Rule, snapshot: dict, evidence: list[str] | None = None) -> AlertOutcome:
    """Map a fired rule to a mode-appropriate, non-executing outcome."""
    ev = evidence or []
    if rule.mode == "manual":
        return AlertOutcome(rule.rule_id, rule.symbol, "notify", "manual",
                            f"{rule.name}: conditions met for {rule.symbol}", ev)
    if rule.mode == "copilot":
        return AlertOutcome(rule.rule_id, rule.symbol, "review_card", "copilot",
                            f"Review: {rule.name} on {rule.symbol}", ev,
                            requires_full_gate_check=True)
    # autopilot -> candidate only; must pass all gates before any execution.
    return AlertOutcome(rule.rule_id, rule.symbol, "candidate", "autopilot",
                        f"Candidate: {rule.name} on {rule.symbol} (pending all gates)", ev,
                        requires_full_gate_check=True)


def evaluate_rules(rules: list[Rule], snapshot: dict) -> list[AlertOutcome]:
    """Evaluate every enabled rule against a snapshot; return outcomes for fires.
    Deduplication (by rule + symbol + window) is applied by the caller/service."""
    outcomes: list[AlertOutcome] = []
    for rule in rules:
        if rule.matches(snapshot):
            evidence = [f"{p.metric} {p.op} {p.value}" for p in rule.predicates]
            outcomes.append(route_outcome(rule, snapshot, evidence))
    return outcomes
