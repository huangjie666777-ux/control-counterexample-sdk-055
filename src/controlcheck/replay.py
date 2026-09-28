"""Concrete semantic replay, independent of the Z3 encoding.

Re-evaluates guards and simultaneous assignments from a model-derived state
sequence so callers can verify the solver witness step by step.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Mapping

from . import expr as E
from .model import Model, ModelError

__all__ = ["ReplayStep", "ReplayResult", "replay", "evaluate", "apply_action"]


@dataclass(frozen=True)
class ReplayStep:
    index: int
    action: str
    guard_held: bool
    in_range: bool
    state_before: Mapping[str, object]
    state_after: Mapping[str, object]


@dataclass(frozen=True)
class ReplayResult:
    ok: bool
    steps: List[ReplayStep]
    errors: List[str]


def evaluate(node: E.Expr, state: Mapping[str, object]):
    if isinstance(node, E.BoolConst):
        return bool(node.value)
    if isinstance(node, E.IntConst):
        return int(node.value)
    if isinstance(node, (E.BoolVar, E.IntVar)):
        return state[node.name]
    if isinstance(node, E.Add):
        return evaluate(node.left, state) + evaluate(node.right, state)
    if isinstance(node, E.Sub):
        return evaluate(node.left, state) - evaluate(node.right, state)
    if isinstance(node, E.Mul):
        return evaluate(node.operand, state) * node.k
    if isinstance(node, E.Cmp):
        left = evaluate(node.left, state)
        right = evaluate(node.right, state)
        return {
            "eq": left == right,
            "ne": left != right,
            "lt": left < right,
            "le": left <= right,
            "gt": left > right,
            "ge": left >= right,
        }[node.op]
    if isinstance(node, E.And):
        return bool(evaluate(node.left, state)) and bool(evaluate(node.right, state))
    if isinstance(node, E.Or):
        return bool(evaluate(node.left, state)) or bool(evaluate(node.right, state))
    if isinstance(node, E.Not):
        return not bool(evaluate(node.operand, state))
    raise TypeError(f"unsupported expression node: {type(node).__name__}")


def in_bounds(model: Model, state: Mapping[str, object]) -> bool:
    for name, decl in model.int_vars.items():
        value = state[name]
        if not decl.lower <= value <= decl.upper:
            return False
    return True


def action_is_enabled(model: Model, action, state: Mapping[str, object]) -> bool:
    if not bool(evaluate(action.guard, state)):
        return False
    candidate = _candidate(model, action, state)
    return in_bounds(model, candidate)


def _candidate(model: Model, action, state: Mapping[str, object]) -> Dict[str, object]:
    new_state = dict(state)
    for name, rhs in action.assignments.items():
        new_state[name] = evaluate(rhs, state)
    return new_state


def apply_action(model: Model, action, state: Mapping[str, object]) -> Dict[str, object]:
    """Simultaneously apply an action; raises if it is not enabled."""
    if not bool(evaluate(action.guard, state)):
        raise ModelError(f"action {action.name!r}: guard does not hold in replay")
    candidate = _candidate(model, action, state)
    for name, decl in model.int_vars.items():
        value = candidate[name]
        if not decl.lower <= value <= decl.upper:
            raise ModelError(
                f"action {action.name!r}: integer {name!r}={value} leaves "
                f"bounds [{decl.lower}, {decl.upper}]"
            )
    return candidate


def replay(
    model: Model,
    init_state: Mapping[str, object],
    action_names: List[str],
    *,
    final_check=None,
) -> ReplayResult:
    """Replay an action sequence and optionally verify a final boolean check.

    Every step checks the guard, simultaneous assignment semantics and
    integer bounds. final_check(state) is invoked on the last state when
    provided and must return True.
    """
    errors: List[str] = []
    steps: List[ReplayStep] = []
    state = dict(init_state)
    by_name = {a.name: a for a in model.actions}

    declared = set(model.bool_vars) | set(model.int_vars)
    if set(state) != declared:
        errors.append(
            f"initial state variables {sorted(state)} do not match declared {sorted(declared)}"
        )
    if not in_bounds(model, state):
        errors.append("initial state violates integer bounds")
    if not bool(evaluate(model.init, state)):
        errors.append("initial state does not satisfy init condition")

    for index, name in enumerate(action_names):
        action = by_name.get(name)
        if action is None:
            errors.append(f"step {index}: unknown action {name!r}")
            steps.append(ReplayStep(index, name, False, False, dict(state), dict(state)))
            continue
        guard_held = bool(evaluate(action.guard, state))
        candidate = _candidate(model, action, state)
        bounded = in_bounds(model, candidate)
        if not guard_held:
            errors.append(f"step {index}: action {name!r} guard was false")
        if not bounded:
            errors.append(f"step {index}: action {name!r} produced out-of-range state")
        steps.append(
            ReplayStep(index, name, guard_held, bounded, dict(state), dict(candidate))
        )
        state = candidate

    if final_check is not None:
        try:
            if not bool(final_check(state)):
                errors.append("final check failed")
        except Exception as exc:
            errors.append(f"final check raised: {exc}")

    return ReplayResult(ok=not errors, steps=steps, errors=errors)
