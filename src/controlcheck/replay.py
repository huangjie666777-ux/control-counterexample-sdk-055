"""Concrete semantic replay.

Re-evaluates a counterexample (or an action sequence) with an
independent plain-Python interpreter of the structured expressions,
so guards, simultaneous assignments, bounds and the property can be
checked against the Z3 trace rather than trusted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Mapping

from .checker import CheckResult, DEADLOCK, SAFETY_VIOLATED, Counterexample
from .expressions import Add, And, Cmp, Const, Expr, Mul, Not, Or, Sub, Var
from .model import Model, _check_bool, validate_model


class ReplayError(Exception):
    """Raised when a claimed counterexample does not match model semantics."""


def evaluate(expr: Expr, state: Mapping[str, object]):
    if isinstance(expr, Var):
        return state[expr.name]
    if isinstance(expr, Const):
        return expr.value
    if isinstance(expr, Add):
        return evaluate(expr.left, state) + evaluate(expr.right, state)
    if isinstance(expr, Sub):
        return evaluate(expr.left, state) - evaluate(expr.right, state)
    if isinstance(expr, Mul):
        return expr.coef * evaluate(expr.expr, state)
    if isinstance(expr, Cmp):
        lhs, rhs = evaluate(expr.left, state), evaluate(expr.right, state)
        return {
            "==": lhs == rhs, "!=": lhs != rhs,
            "<": lhs < rhs, "<=": lhs <= rhs,
            ">": lhs > rhs, ">=": lhs >= rhs,
        }[expr.op]
    if isinstance(expr, And):
        return all(evaluate(a, state) for a in expr.args)
    if isinstance(expr, Or):
        return any(evaluate(a, state) for a in expr.args)
    if isinstance(expr, Not):
        return not evaluate(expr.arg, state)
    raise ReplayError(f"cannot evaluate {expr!r}")


def step(model: Model, state: Mapping[str, object], action: Action) -> dict:
    """Apply one action, reading all right-hand sides from the old state."""
    if not evaluate(action.guard, state):
        raise ReplayError(f"action {action.name!r} guard is false at state {state}")
    next_state = dict(state)
    new_values = {}
    for target, rhs in action.assigns.items():
        new_values[target] = evaluate(rhs, state)
    for target, value in new_values.items():
        if target in model.int_vars:
            lo, hi = model.int_vars[target]
            if not lo <= value <= hi:
                raise ReplayError(
                    f"action {action.name!r} pushes {target}={value} out of [{lo}, {hi}]"
                )
        next_state[target] = value
    return next_state


def replay_sequence(model: Model, initial_state: Mapping[str, object],
                    action_names: List[str]) -> List[dict]:
    """Simulate an action sequence from a given concrete state."""
    validate_model(model)
    by_name = {a.name: a for a in model.actions}
    states = [dict(initial_state)]
    for name in action_names:
        if name not in by_name:
            raise ReplayError(f"unknown action {name!r}")
        states.append(step(model, states[-1], by_name[name]))
    return states


@dataclass
class ReplayTrace:
    states: List[dict]
    actions: List[str]
    reason: str


def verify_counterexample(model: Model, result: CheckResult,
                          property: Expr = None) -> ReplayTrace:
    """Independently re-execute a found counterexample and confirm failure.

    Raises ReplayError if the trace does not satisfy the model semantics.
    """
    validate_model(model)
    cex: Counterexample = result.counterexample
    if cex is None:
        raise ReplayError("result has no counterexample to verify")

    states = replay_sequence(model, cex.states[0], cex.actions)
    if states != [dict(s) for s in cex.states]:
        raise ReplayError("replayed states do not match the counterexample trace")

    last = states[-1]
    if cex.reason == SAFETY_VIOLATED:
        if property is None:
            raise ReplayError("safety counterexample requires the property to verify")
        _check_bool(model, property, "safety property")
        if evaluate(property, last):
            raise ReplayError("property holds at the claimed violating state")
    elif cex.reason == DEADLOCK:
        for a in model.actions:
            executable = evaluate(a.guard, last)
            if executable:
                for target, rhs in a.assigns.items():
                    if target in model.int_vars:
                        lo, hi = model.int_vars[target]
                        v = evaluate(rhs, last)
                        if not lo <= v <= hi:
                            executable = False
            if executable:
                raise ReplayError(
                    f"state is not a deadlock: action {a.name!r} is executable"
                )
        if evaluate(model.terminal, last):
            raise ReplayError("state is terminal, so deadlock is not a failure")
    else:
        raise ReplayError(f"unknown counterexample reason {cex.reason!r}")
    return ReplayTrace(states, list(cex.actions), cex.reason)
