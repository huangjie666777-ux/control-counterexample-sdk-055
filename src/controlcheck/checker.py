"""Bounded model checking over the symbolic unrolling.

Searches for the shortest counterexample within a caller-supplied step
bound. Each check builds a fresh solver, so checks never pollute each
other and the caller's model is never mutated.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import z3

from .encoder import StepEncoder, decode_state, encode_expr
from .expressions import BoolExpr, ModelError, Var
from .model import Model, validate_model, _check_bool

COUNTEREXAMPLE = "counterexample"
NO_COUNTEREXAMPLE_IN_BOUND = "no_counterexample_within_bound"
INIT_UNSAT = "init_unsat"
UNKNOWN = "unknown"

SAFETY_VIOLATED = "safety_violated"
DEADLOCK = "deadlock"


@dataclass
class Counterexample:
    states: List[dict]          # full state at every step, including the last
    actions: List[str]          # action taken from states[i] to states[i+1]
    reason: str                 # SAFETY_VIOLATED or DEADLOCK

    @property
    def length(self) -> int:
        return len(self.actions)


@dataclass
class CheckResult:
    status: str
    bound: int
    counterexample: Optional[Counterexample] = None

    @property
    def ok_within_bound(self) -> bool:
        return self.status == NO_COUNTEREXAMPLE_IN_BOUND


def _new_solver(timeout_ms: Optional[int]) -> z3.Solver:
    solver = z3.Solver()
    if timeout_ms is not None:
        solver.set("timeout", timeout_ms)
    return solver


def _check_init_satisfiable(model: Model, timeout_ms: Optional[int]) -> str:
    enc = StepEncoder(model)
    solver = _new_solver(timeout_ms)
    ctx = enc.state_vars(0)
    solver.add(enc.domain_constraints(ctx))
    solver.add(encode_expr(model.init, ctx))
    res = solver.check()
    if res == z3.sat:
        return "sat"
    if res == z3.unsat:
        return "unsat"
    return "unknown"


def _run_search(model, bound, failure_at, timeout_ms) -> CheckResult:
    enc = StepEncoder(model)
    for k in range(bound + 1):
        solver = _new_solver(timeout_ms)
        ctxs = [enc.state_vars(i) for i in range(k + 1)]
        solver.add(enc.domain_constraints(ctxs[0]))
        solver.add(encode_expr(model.init, ctxs[0]))
        for i in range(k):
            trans, _ = enc.transition(i, ctxs[i], ctxs[i + 1])
            solver.add(trans)
            solver.add(enc.domain_constraints(ctxs[i + 1]))
            # shortest counterexample: no failure at earlier steps
            solver.add(z3.Not(failure_at(enc, ctxs[i])))
        solver.add(failure_at(enc, ctxs[k]))
        res = solver.check()
        if res == z3.sat:
            zm = solver.model()
            states = [decode_state(zm, c) for c in ctxs]
            actions = []
            for i in range(k):
                fired = next(
                    a.name
                    for a in model.actions
                    if z3.is_true(zm.eval(enc.action_executable(a, ctxs[i]), model_completion=True))
                    and all(
                        z3.is_true(
                            zm.eval(
                                ctxs[i + 1][n] == encode_expr(a.assigns.get(n, Var(n)), ctxs[i]),
                                model_completion=True,
                            )
                        )
                        for n in enc.names
                    )
                )
                actions.append(fired)
            return CheckResult(COUNTEREXAMPLE, bound,
                               Counterexample(states, actions, failure_at.reason))
        if res == z3.unknown:
            return CheckResult(UNKNOWN, bound)
    return CheckResult(NO_COUNTEREXAMPLE_IN_BOUND, bound)


def _validate_bound(bound: int) -> None:
    if isinstance(bound, bool) or not isinstance(bound, int) or bound < 0:
        raise ModelError(f"step bound must be a non-negative integer, got {bound!r}")


def check_safety(model: Model, bound: int, property: BoolExpr,
                 timeout_ms: Optional[int] = None) -> CheckResult:
    """Check that the property holds in every reachable state up to bound
    steps, including the initial state. Returns the shortest violation."""
    validate_model(model)
    _validate_bound(bound)
    _check_bool(model, property, "safety property")
    init = _check_init_satisfiable(model, timeout_ms)
    if init == "unsat":
        return CheckResult(INIT_UNSAT, bound)
    if init == "unknown":
        return CheckResult(UNKNOWN, bound)

    def failure_at(enc, ctx):
        return z3.Not(encode_expr(property, ctx))
    failure_at.reason = SAFETY_VIOLATED
    return _run_search(model, bound, failure_at, timeout_ms)


def check_deadlock(model: Model, bound: int,
                   timeout_ms: Optional[int] = None) -> CheckResult:
    """Check for a reachable non-terminal state with no legal successor."""
    validate_model(model)
    _validate_bound(bound)
    init = _check_init_satisfiable(model, timeout_ms)
    if init == "unsat":
        return CheckResult(INIT_UNSAT, bound)
    if init == "unknown":
        return CheckResult(UNKNOWN, bound)

    def failure_at(enc, ctx):
        return enc.deadlock_at(ctx)
    failure_at.reason = DEADLOCK
    return _run_search(model, bound, failure_at, timeout_ms)
