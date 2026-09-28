"""Public SDK facade: model construction, checks, and verified replay."""
from __future__ import annotations

from typing import List, Optional

from . import expr as E
from .checker import (
    CheckKind,
    CheckResult,
    CheckStatus,
    Counterexample,
    Step,
    check_deadlock as _check_deadlock,
    check_safety as _check_safety,
)
from .model import Action, BoolVarDecl, IntVarDecl, Model, ModelError
from .replay import (
    ReplayResult,
    apply_action,
    evaluate,
    replay as _replay,
)

__all__ = [
    "Action", "BoolVarDecl", "IntVarDecl", "Model", "ModelError",
    "CheckKind", "CheckStatus", "CheckResult", "Counterexample", "Step",
    "ReplayResult",
    "check_safety", "check_deadlock", "verify_counterexample",
    "replay", "evaluate", "apply_action",
]


def check_safety(model: Model, safety: E.BoolExpr, bound: int,
                 timeout_ms: Optional[int] = None) -> CheckResult:
    """Bounded safety check; the model is re-validated up front."""
    return _check_safety(_revalidate(model), safety, bound, timeout_ms)


def check_deadlock(model: Model, bound: int,
                   timeout_ms: Optional[int] = None) -> CheckResult:
    """Bounded deadlock check; the model is re-validated up front."""
    return _check_deadlock(_revalidate(model), bound, timeout_ms)


def _revalidate(model: Model) -> Model:
    if not isinstance(model, Model):
        raise ModelError("expected a validated Model instance")
    return Model(
        variables=list(model.variables),
        init=model.init,
        exit=model.exit,
        actions=[
            Action(name=a.name, guard=a.guard, assignments=dict(a.assignments))
            for a in model.actions
        ],
    )


def verify_counterexample(
    model: Model,
    counterexample: Counterexample,
    safety: Optional[E.BoolExpr] = None,
) -> ReplayResult:
    """Independently replay a returned counterexample with concrete semantics.

    Checks: init condition and bounds, per-step guards, simultaneous updates
    matching reported states, and the terminal failure (safety false, or
    non-terminal state with no enabled action).
    """
    if counterexample.kind is CheckKind.SAFETY and safety is None:
        raise ValueError("safety expression is required to replay a safety witness")

    init_state = counterexample.steps[0].state
    action_names: List[str] = [
        step.action for step in counterexample.steps if step.action is not None
    ]

    def final_check(snapshot) -> bool:
        if counterexample.kind is CheckKind.SAFETY:
            return not bool(evaluate(safety, snapshot))
        from .replay import action_is_enabled
        if bool(evaluate(model.exit, snapshot)):
            return False
        return not any(
            action_is_enabled(model, action, snapshot) for action in model.actions
        )

    result = _replay(model, init_state, action_names, final_check=final_check)
    errors = list(result.errors)
    reported_pairs = [
        (step.action, step.state) for step in counterexample.steps[1:]
    ]
    for step_index, (_, reported_after) in enumerate(reported_pairs):
        actual_after = result.steps[step_index].state_after
        if actual_after != dict(reported_after):
            errors.append(
                f"step {step_index + 1}: reported state {reported_after} differs "
                f"from semantic replay {actual_after}"
            )
    return ReplayResult(ok=not errors, steps=result.steps, errors=errors)


def replay(model: Model, init_state, action_names, *, final_check=None) -> ReplayResult:
    """Concrete replay of named actions from a complete state."""
    return _replay(model, init_state, action_names, final_check=final_check)
