"""Control-logic bounded verification SDK.

Modules:
  * expr/model: declarative AST and validated immutable model
  * encoding: Z3 symbolic unrolling
  * checker: bounded shortest-witness search
  * replay/sdk: concrete replay and public facade
"""
from __future__ import annotations

from .expr import (
    FALSE,
    TRUE,
    Add,
    And,
    BoolConst,
    BoolExpr,
    BoolVar,
    Cmp,
    Expr,
    IntConst,
    IntExpr,
    IntVar,
    Mul,
    Not,
    Or,
    Sub,
    c,
    eq,
    ne,
    lt,
    le,
    gt,
    ge,
    var,
)
from .model import Action, BoolVarDecl, IntVarDecl, Model, ModelError
from .checker import (
    CheckKind,
    CheckResult,
    CheckStatus,
    Counterexample,
    Step,
)
from .replay import ReplayResult
from .sdk import (
    apply_action,
    check_deadlock,
    check_safety,
    evaluate,
    replay,
    verify_counterexample,
)

__all__ = [
    # expressions
    "Expr", "BoolExpr", "IntExpr", "BoolConst", "IntConst", "BoolVar", "IntVar",
    "Add", "Sub", "Mul", "Cmp", "And", "Or", "Not", "TRUE", "FALSE", "var", "c",
    "eq", "ne", "lt", "le", "gt", "ge",
    # model
    "Model", "Action", "BoolVarDecl", "IntVarDecl", "ModelError",
    # checks
    "CheckKind", "CheckStatus", "CheckResult", "Counterexample", "Step",
    "ReplayResult",
    "check_safety", "check_deadlock", "verify_counterexample",
    "replay", "evaluate", "apply_action",
]
