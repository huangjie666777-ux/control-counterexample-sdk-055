"""Bounded checking SDK for industrial interlock/control logic.

Public interface:

- Model builders: Model, Action and structured expression constructors.
- Checks: check_safety, check_deadlock.
- Results: CheckResult, Counterexample, status/reason constants.
- Replay: replay_sequence, verify_counterexample.
- Errors: ModelError, ReplayError.
"""

from .expressions import (
    Add,
    And,
    BoolExpr,
    Cmp,
    Const,
    Expr,
    IntExpr,
    ModelError,
    Mul,
    Not,
    Or,
    Sub,
    Var,
)
from .model import Action, Model, validate_model
from .checker import (
    COUNTEREXAMPLE,
    DEADLOCK,
    INIT_UNSAT,
    NO_COUNTEREXAMPLE_IN_BOUND,
    SAFETY_VIOLATED,
    UNKNOWN,
    CheckResult,
    Counterexample,
    check_deadlock,
    check_safety,
)
from .replay import ReplayError, replay_sequence, verify_counterexample

__all__ = [
    "Expr", "BoolExpr", "IntExpr", "Var", "Const", "Add", "Sub", "Mul",
    "Cmp", "And", "Or", "Not",
    "Action", "Model", "validate_model", "ModelError",
    "check_safety", "check_deadlock",
    "CheckResult", "Counterexample",
    "COUNTEREXAMPLE", "NO_COUNTEREXAMPLE_IN_BOUND", "INIT_UNSAT", "UNKNOWN",
    "SAFETY_VIOLATED", "DEADLOCK",
    "replay_sequence", "verify_counterexample", "ReplayError",
]
