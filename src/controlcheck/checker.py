"""Bounded symbolic search: safety violations and deadlocks, shortest first.

Each check builds its own fresh Z3 solver/constants, so runs never pollute one
another. Results never claim global safety: only satisfaction within the
caller-supplied step bound.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

import z3

from . import expr as E
from .encoding import EncodedModel, State
from .model import Model

__all__ = [
    "CheckStatus", "CheckKind", "Step", "Counterexample", "CheckResult",
    "check_safety", "check_deadlock",
]


class CheckStatus(str, Enum):
    NO_COUNTEREXAMPLE_IN_BOUND = "no_counterexample_in_bound"
    COUNTEREXAMPLE = "counterexample"
    INIT_UNSAT = "init_unsat"
    UNKNOWN = "unknown"
    TIMEOUT = "timeout"
    INVALID_BOUND = "invalid_bound"


class CheckKind(str, Enum):
    SAFETY = "safety"
    DEADLOCK = "deadlock"


@dataclass(frozen=True)
class Step:
    index: int
    action: Optional[str]
    state: Dict[str, object]


@dataclass(frozen=True)
class Counterexample:
    kind: CheckKind
    length: int
    steps: List[Step]
    failure_reason: str
    final_state: Dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class CheckResult:
    kind: CheckKind
    status: CheckStatus
    bound: int
    counterexample: Optional[Counterexample] = None
    reason: str = ""

    @property
    def has_counterexample(self) -> bool:
        return self.counterexample is not None


def _model_state(encoded: EncodedModel, state: State, z3model: z3.ModelRef) -> Dict[str, object]:
    out: Dict[str, object] = {}
    for name, ref in state.bools.items():
        out[name] = bool(z3.is_true(z3model.eval(ref, model_completion=True)))
    for name, ref in state.ints.items():
        out[name] = int(z3model.eval(ref, model_completion=True).as_long())
    return out


def _add_step(encoded: EncodedModel, solver: z3.Solver, src: State, dst: State):
    guards, branches, fires, exactly_one = encoded.step(src, dst)
    solver.add(*encoded.encoding.bounds(src))
    solver.add(*encoded.encoding.bounds(dst))
    solver.add(z3.Or(*branches))
    solver.add(exactly_one)
    return fires


def _eval_bool(node, snapshot, encoded: EncodedModel) -> bool:
    from .replay import evaluate
    return bool(evaluate(node, snapshot))


def _action_enabled(encoded: EncodedModel, action, snapshot) -> bool:
    from .replay import action_is_enabled
    return action_is_enabled(encoded.model, action, snapshot)


def _extract_trace(encoded, solver, kind, states, guards_per_step, length):
    z3model = solver.model()
    actions = encoded.model.actions
    names: List[Optional[str]] = []
    for i in range(length):
        for action, fire in zip(actions, guards_per_step[i]):
            if z3.is_true(z3model.eval(fire, model_completion=True)):
                names.append(action.name)
                break
        else:
            names.append(None)

    steps: List[Step] = []
    for i in range(length + 1):
        snapshot = _model_state(encoded, states[i], z3model)
        # names[t] is the action that produced state t+1 from state t.
        action_name = None if i == 0 else names[i - 1]
        steps.append(Step(index=i, action=action_name, state=snapshot))

    final = steps[-1].state
    if kind is CheckKind.SAFETY:
        reason = "safety condition is false at this reachable state"
    else:
        exit_held = bool(_eval_bool(encoded.model.exit, final, encoded))
        if exit_held:
            reason = "internal error: flagged state actually satisfies exit"
        else:
            enabled = [a.name for a in actions if _action_enabled(encoded, a, final)]
            reason = (
                "non-terminal state has no legal enabled action"
                if not enabled
                else f"internal error: enabled actions reported: {enabled}"
            )
    return Counterexample(kind=kind, length=length, steps=steps,
                          failure_reason=reason, final_state=dict(final))


def _run(model, kind, bound, timeout_ms, safety) -> CheckResult:
    if isinstance(bound, bool) or not isinstance(bound, int) or bound < 0:
        return CheckResult(
            kind=kind,
            status=CheckStatus.INVALID_BOUND,
            bound=bound if isinstance(bound, int) else -1,
            reason="bound must be a non-negative integer",
        )
    if kind is CheckKind.SAFETY and safety is None:
        raise ValueError("safety check requires a boolean safety condition")

    encoded = EncodedModel(model)
    init_solver = z3.Solver()
    if timeout_ms is not None:
        init_solver.set("timeout", int(timeout_ms))
    s0 = encoded.encoding.fresh_state(0)
    init_solver.add(*encoded.init_constraints(s0))
    verdict = init_solver.check()
    if verdict == z3.unsat:
        return CheckResult(
            kind=kind,
            status=CheckStatus.INIT_UNSAT,
            bound=bound,
            reason="init condition has no legal state; no path starts",
        )
    if verdict == z3.unknown:
        status = (
            CheckStatus.TIMEOUT
            if init_solver.reason_unknown() == "timeout"
            else CheckStatus.UNKNOWN
        )
        return CheckResult(
            kind=kind, status=status, bound=bound,
            reason=f"init feasibility unknown: {init_solver.reason_unknown()}",
        )

    for length in range(0, bound + 1):
        solver = z3.Solver()
        if timeout_ms is not None:
            solver.set("timeout", int(timeout_ms))
        states = [encoded.encoding.fresh_state(i) for i in range(length + 1)]
        solver.add(*encoded.init_constraints(states[0]))
        guards_per_step = []
        for i in range(length):
            guards = _add_step(encoded, solver, states[i], states[i + 1])
            guards_per_step.append(guards)

        if kind is CheckKind.SAFETY:
            targets = [
                z3.Not(encoded.safety_expr(safety, states[i]))
                for i in range(length + 1)
            ]
            solver.add(z3.Or(*targets))
        else:
            non_terminal = z3.Not(encoded.exit_expr(states[length]))
            guards_here = encoded.enabled_guards(states[length])
            deadlock = z3.And([non_terminal, z3.Not(z3.Or(*guards_here))])
            solver.add(deadlock)

        verdict = solver.check()
        if verdict == z3.sat:
            cex = _extract_trace(encoded, solver, kind, states,
                                guards_per_step, length)
            return CheckResult(kind=kind, status=CheckStatus.COUNTEREXAMPLE,
                               bound=bound, counterexample=cex)
        if verdict == z3.unknown:
            status = (
                CheckStatus.TIMEOUT
                if solver.reason_unknown() == "timeout"
                else CheckStatus.UNKNOWN
            )
            return CheckResult(
                kind=kind, status=status, bound=bound,
                reason=(
                    f"solver unknown at length {length} "
                    f"({solver.reason_unknown()}); shorter lengths were ruled out"
                ),
            )

    scope = (
        f"no reachable state within {bound} step(s) violates the safety condition"
        if kind is CheckKind.SAFETY
        else f"no non-terminal deadlock reachable within {bound} step(s)"
    )
    return CheckResult(kind=kind,
                       status=CheckStatus.NO_COUNTEREXAMPLE_IN_BOUND,
                       bound=bound, reason=scope)


def check_safety(model: Model, safety: E.BoolExpr, bound: int,
                 timeout_ms: Optional[int] = None) -> CheckResult:
    """Search 0..bound steps for a reachable state falsifying the condition."""
    return _run(model, CheckKind.SAFETY, bound, timeout_ms, safety)


def check_deadlock(model: Model, bound: int,
                   timeout_ms: Optional[int] = None) -> CheckResult:
    """Search 0..bound steps for a non-terminal state with no legal successor."""
    return _run(model, CheckKind.DEADLOCK, bound, timeout_ms, None)
