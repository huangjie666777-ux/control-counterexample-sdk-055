"""Model definition and validation.

A model has named boolean variables, bounded integer variables, an
initial condition, a terminal condition, and uniquely named actions.
Each action has a guard and a set of simultaneous assignments.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Tuple

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


@dataclass(frozen=True)
class Action:
    name: str
    guard: BoolExpr
    assigns: Mapping[str, Expr] = field(default_factory=dict)


@dataclass(frozen=True)
class Model:
    bool_vars: Tuple[str, ...]
    int_vars: Mapping[str, Tuple[int, int]]  # name -> (lo, hi), inclusive
    init: BoolExpr
    terminal: BoolExpr
    actions: Tuple[Action, ...]

    def __post_init__(self) -> None:
        validate_model(self)

    def var_type(self, name: str) -> str:
        if name in self.bool_vars:
            return "bool"
        if name in self.int_vars:
            return "int"
        raise ModelError(f"unknown variable {name!r}")


def _type_of(model: Model, expr: Expr) -> str:
    """Infer and check the type of an expression against the model."""
    if isinstance(expr, Var):
        return model.var_type(expr.name)
    if isinstance(expr, Const):
        return "bool" if isinstance(expr.value, bool) else "int"
    if isinstance(expr, (Add, Sub)):
        lt, rt = _type_of(model, expr.left), _type_of(model, expr.right)
        if lt != "int" or rt != "int":
            raise ModelError(f"arithmetic operand must be int in {expr!r}")
        return "int"
    if isinstance(expr, Mul):
        if _type_of(model, expr.expr) != "int":
            raise ModelError(f"Mul operand must be int in {expr!r}")
        return "int"
    if isinstance(expr, Cmp):
        lt, rt = _type_of(model, expr.left), _type_of(model, expr.right)
        if lt != rt:
            raise ModelError(f"comparison of mismatched types in {expr!r}")
        if lt != "int" and expr.op not in ("==", "!="):
            raise ModelError(f"operator {expr.op!r} requires int operands in {expr!r}")
        return "bool"
    if isinstance(expr, (And, Or)):
        for a in expr.args:
            if _type_of(model, a) != "bool":
                raise ModelError(f"boolean combinator operand must be bool in {expr!r}")
        return "bool"
    if isinstance(expr, Not):
        if _type_of(model, expr.arg) != "bool":
            raise ModelError(f"Not operand must be bool in {expr!r}")
        return "bool"
    raise ModelError(f"unsupported expression node {expr!r}")


def _check_bool(model: Model, expr: Expr, what: str) -> None:
    if not isinstance(expr, Expr):
        raise ModelError(f"{what} must be a structured expression, got {expr!r}")
    if _type_of(model, expr) != "bool":
        raise ModelError(f"{what} must be a boolean expression")


def validate_model(model: Model) -> Model:
    """Validate structure, references and types. Returns the model unchanged."""
    if not isinstance(model, Model):
        raise ModelError(f"expected a Model, got {model!r}")
    if not isinstance(model.bool_vars, tuple) or not all(
        isinstance(n, str) for n in model.bool_vars
    ):
        raise ModelError("bool_vars must be a tuple of names")
    if not isinstance(model.int_vars, Mapping):
        raise ModelError("int_vars must be a mapping of name to (lo, hi)")
    if not isinstance(model.actions, tuple):
        raise ModelError("actions must be a tuple of Action")

    seen = set()
    for name in model.bool_vars:
        if not isinstance(name, str) or not name:
            raise ModelError(f"invalid variable name {name!r}")
        if name in seen:
            raise ModelError(f"duplicate variable name {name!r}")
        seen.add(name)
    for name, bounds in model.int_vars.items():
        if not isinstance(name, str) or not name:
            raise ModelError(f"invalid variable name {name!r}")
        if name in seen:
            raise ModelError(f"duplicate variable name {name!r}")
        seen.add(name)
        lo, hi = bounds
        if isinstance(lo, bool) or isinstance(hi, bool) or not isinstance(lo, int) or not isinstance(hi, int):
            raise ModelError(f"bounds of {name!r} must be integers")
        if lo > hi:
            raise ModelError(f"empty domain for variable {name!r}: [{lo}, {hi}]")

    _check_bool(model, model.init, "initial condition")
    _check_bool(model, model.terminal, "terminal condition")

    action_names = set()
    for action in model.actions:
        if not isinstance(action, Action):
            raise ModelError(f"invalid action {action!r}")
        if not isinstance(action.name, str) or not action.name:
            raise ModelError(f"invalid action name {action.name!r}")
        if action.name in action_names:
            raise ModelError(f"duplicate action name {action.name!r}")
        action_names.add(action.name)
        _check_bool(model, action.guard, f"guard of action {action.name!r}")
        for target, rhs in action.assigns.items():
            vtype = model.var_type(target)  # raises for unknown target
            if not isinstance(rhs, Expr):
                raise ModelError(
                    f"assignment to {target!r} in action {action.name!r} must be an expression"
                )
            rtype = _type_of(model, rhs)
            if rtype != vtype:
                raise ModelError(
                    f"assignment type mismatch for {target!r} in action {action.name!r}: "
                    f"{rtype} assigned to {vtype} variable"
                )
    return model
