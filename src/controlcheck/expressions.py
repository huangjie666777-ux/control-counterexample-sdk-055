"""Structured expression AST for control-logic models.

Expressions are pure data. They are never produced by evaluating caller
code; callers build them through the constructors below.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union


class ModelError(Exception):
    """Raised when a model or expression is invalid."""


class Expr:
    """Base class of all expressions."""

    def vars(self) -> set[str]:
        raise NotImplementedError


class IntExpr(Expr):
    pass


class BoolExpr(Expr):
    pass


@dataclass(frozen=True)
class Var(Expr):
    """Reference to a variable. Type is resolved against the model."""

    name: str

    def vars(self) -> set[str]:
        return {self.name}


@dataclass(frozen=True)
class Const(Expr):
    """Literal constant, either bool or int."""

    value: Union[bool, int]

    def __post_init__(self) -> None:
        if not isinstance(self.value, (bool, int)):
            raise ModelError(f"Const value must be bool or int, got {self.value!r}")

    def vars(self) -> set[str]:
        return set()


@dataclass(frozen=True)
class Add(IntExpr):
    left: IntExpr
    right: IntExpr

    def vars(self) -> set[str]:
        return self.left.vars() | self.right.vars()


@dataclass(frozen=True)
class Sub(IntExpr):
    left: IntExpr
    right: IntExpr

    def vars(self) -> set[str]:
        return self.left.vars() | self.right.vars()


@dataclass(frozen=True)
class Mul(IntExpr):
    """Multiplication by an integer constant (keeps the theory linear)."""

    coef: int
    expr: IntExpr

    def __post_init__(self) -> None:
        if isinstance(self.coef, bool) or not isinstance(self.coef, int):
            raise ModelError(f"Mul coefficient must be an int constant, got {self.coef!r}")

    def vars(self) -> set[str]:
        return self.expr.vars()


_CMP_OPS = ("==", "!=", "<", "<=", ">", ">=")


@dataclass(frozen=True)
class Cmp(BoolExpr):
    """Comparison. Arithmetic comparisons on int exprs; ==/!= also on bools."""

    op: str
    left: Expr
    right: Expr

    def __post_init__(self) -> None:
        if self.op not in _CMP_OPS:
            raise ModelError(f"unknown comparison operator {self.op!r}")

    def vars(self) -> set[str]:
        return self.left.vars() | self.right.vars()


@dataclass(frozen=True)
class And(BoolExpr):
    args: tuple

    def __init__(self, *args: BoolExpr) -> None:
        if not args:
            raise ModelError("And requires at least one argument")
        object.__setattr__(self, "args", tuple(args))

    def vars(self) -> set[str]:
        out: set[str] = set()
        for a in self.args:
            out |= a.vars()
        return out


@dataclass(frozen=True)
class Or(BoolExpr):
    args: tuple

    def __init__(self, *args: BoolExpr) -> None:
        if not args:
            raise ModelError("Or requires at least one argument")
        object.__setattr__(self, "args", tuple(args))

    def vars(self) -> set[str]:
        out: set[str] = set()
        for a in self.args:
            out |= a.vars()
        return out


@dataclass(frozen=True)
class Not(BoolExpr):
    arg: BoolExpr

    def vars(self) -> set[str]:
        return self.arg.vars()
