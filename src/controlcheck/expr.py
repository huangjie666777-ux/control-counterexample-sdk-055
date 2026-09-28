"""Structured expression AST for the control-logic bounded checker.

Expressions are plain declarative data (frozen dataclasses). They are never
passed to compile()/eval(), so building a model never executes caller code.

Expression kinds:
  * boolean values: bool var/const, comparisons, & / | / ~
  * integer values: int var/const, +, -, * by an integer constant

Operator overloads are intentionally limited to the supported structure:
multiplication only accepts a plain integer constant.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Union

__all__ = [
    "Expr", "BoolExpr", "IntExpr",
    "BoolConst", "BoolVar", "IntConst", "IntVar",
    "Add", "Sub", "Mul", "Cmp", "And", "Or", "Not",
    "TRUE", "FALSE", "var", "c", "eq", "ne", "lt", "le", "gt", "ge",
]


class Expr:
    """Root of the expression tree. dtype is 'bool' or 'int'."""

    dtype: ClassVar[str]


class BoolExpr(Expr):
    dtype: ClassVar[str] = "bool"

    def __and__(self, other: "BoolExpr") -> "And":
        return And(self, _as_bool(other))

    def __or__(self, other: "BoolExpr") -> "Or":
        return Or(self, _as_bool(other))

    def __invert__(self) -> "Not":
        return Not(self)


class IntExpr(Expr):
    dtype: ClassVar[str] = "int"

    def __add__(self, other) -> "Add":
        return Add(self, _as_int(other))

    def __radd__(self, other) -> "Add":
        return Add(_as_int(other), self)

    def __sub__(self, other) -> "Sub":
        return Sub(self, _as_int(other))

    def __rsub__(self, other) -> "Sub":
        return Sub(_as_int(other), self)

    def __neg__(self) -> "Sub":
        return Sub(IntConst(0), self)

    def __mul__(self, k: int) -> "Mul":
        return Mul(self, _as_const_int(k))

    __rmul__ = __mul__

    def _cmp(self, op: str, other: object) -> "Cmp":
        if isinstance(other, bool):
            raise TypeError("cannot compare integer expression with bool")
        if isinstance(other, int):
            return Cmp(op, self, IntConst(other))
        if isinstance(other, IntExpr):
            return Cmp(op, self, other)
        raise TypeError(f"cannot compare integer expression with {other!r}")

    def _rcmp(self, op: str, other: object) -> "Cmp":
        swapped = {"eq": "eq", "ne": "ne", "lt": "gt", "le": "ge",
                   "gt": "lt", "ge": "le"}[op]
        return self._cmp(swapped, other)

    def __eq__(self, other: object) -> "Cmp":  # type: ignore[override]
        return self._cmp("eq", other)

    def __ne__(self, other: object) -> "Cmp":  # type: ignore[override]
        return Cmp("ne", self, _as_int(other))

    def __lt__(self, other: object) -> "Cmp":
        return self._cmp("lt", other)

    def __le__(self, other: object) -> "Cmp":
        return self._cmp("le", other)

    def __gt__(self, other: object) -> "Cmp":
        return self._cmp("gt", other)

    def __ge__(self, other: object) -> "Cmp":
        return self._cmp("ge", other)

    def __hash__(self) -> int:  # type: ignore[override]
        return id(self)


@dataclass(frozen=True)
class BoolConst(BoolExpr):
    value: bool


@dataclass(frozen=True)
class IntConst(IntExpr):
    value: int


@dataclass(frozen=True)
class BoolVar(BoolExpr):
    name: str


@dataclass(frozen=True)
class IntVar(IntExpr):
    name: str


@dataclass(frozen=True)
class Add(IntExpr):
    left: IntExpr
    right: IntExpr


@dataclass(frozen=True)
class Sub(IntExpr):
    left: IntExpr
    right: IntExpr


@dataclass(frozen=True)
class Mul(IntExpr):
    """Multiplication where k must be a compile-time integer."""

    operand: IntExpr
    k: int


_CMP_OPS = frozenset({"eq", "ne", "lt", "le", "gt", "ge"})


@dataclass(frozen=True)
class Cmp(BoolExpr):
    op: str
    left: IntExpr
    right: IntExpr

    def __post_init__(self) -> None:
        if self.op not in _CMP_OPS:
            raise ValueError(f"unsupported comparison op: {self.op!r}")


@dataclass(frozen=True)
class And(BoolExpr):
    left: BoolExpr
    right: BoolExpr


@dataclass(frozen=True)
class Or(BoolExpr):
    left: BoolExpr
    right: BoolExpr


@dataclass(frozen=True)
class Not(BoolExpr):
    operand: BoolExpr


TRUE: BoolConst = BoolConst(True)
FALSE: BoolConst = BoolConst(False)


def var(dtype, name: str) -> Expr:
    """Build a typed variable reference, e.g. var(bool, 'x')."""
    if dtype is bool or dtype == "bool":
        return BoolVar(name)
    if dtype is int or dtype == "int":
        return IntVar(name)
    raise TypeError("dtype must be bool or int")


def c(value) -> Expr:
    """Build a typed constant."""
    if isinstance(value, bool):
        return BoolConst(value)
    if isinstance(value, int):
        return IntConst(value)
    raise TypeError("constant must be bool or int")


def _pair(left, right):
    return _as_int(left), _as_int(right)


def eq(left, right) -> "Cmp":
    a, b = _pair(left, right)
    return Cmp("eq", a, b)


def ne(left, right) -> "Cmp":
    a, b = _pair(left, right)
    return Cmp("ne", a, b)


def lt(left, right) -> "Cmp":
    a, b = _pair(left, right)
    return Cmp("lt", a, b)


def le(left, right) -> "Cmp":
    a, b = _pair(left, right)
    return Cmp("le", a, b)


def gt(left, right) -> "Cmp":
    a, b = _pair(left, right)
    return Cmp("gt", a, b)


def ge(left, right) -> "Cmp":
    a, b = _pair(left, right)
    return Cmp("ge", a, b)


def _as_bool(value: object) -> BoolExpr:
    if isinstance(value, bool):
        return BoolConst(value)
    if isinstance(value, BoolExpr):
        return value
    raise TypeError(f"expected boolean expression, got {value!r}")


def _as_int(value: object) -> IntExpr:
    if isinstance(value, bool):
        raise TypeError("bool is not an int expression; wrap it explicitly")
    if isinstance(value, int):
        return IntConst(value)
    if isinstance(value, IntExpr):
        return value
    raise TypeError(f"expected integer expression, got {value!r}")


def _as_const_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("multiplication is only supported by an integer constant")
    return value
