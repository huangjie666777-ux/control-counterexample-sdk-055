"""Control model definition and structural validation."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Dict, Mapping, Sequence

from . import expr as E

__all__ = [
    "ModelError", "BoolVarDecl", "IntVarDecl", "Action", "Model",
]


class ModelError(ValueError):
    """Raised when a model is structurally, referentially, or type invalid."""


def _id_ok(name: object) -> bool:
    return (
        isinstance(name, str)
        and name != ""
        and all(ch.isalnum() or ch == "_" for ch in name)
    )


@dataclass(frozen=True)
class BoolVarDecl:
    name: str


@dataclass(frozen=True)
class IntVarDecl:
    name: str
    lower: int
    upper: int

    def __post_init__(self) -> None:
        if not isinstance(self.lower, int) or isinstance(self.lower, bool):
            raise ModelError(f"integer variable {self.name!r}: lower bound must be int")
        if not isinstance(self.upper, int) or isinstance(self.upper, bool):
            raise ModelError(f"integer variable {self.name!r}: upper bound must be int")
        if self.lower > self.upper:
            raise ModelError(
                f"integer variable {self.name!r}: lower bound {self.lower} "
                f"exceeds upper bound {self.upper}"
            )


@dataclass(frozen=True)
class Action:
    """A named guarded transition.

    Guard and every assignment RHS read the pre-action state; assignments are
    applied simultaneously.
    """

    name: str
    guard: E.BoolExpr
    assignments: Mapping[str, E.Expr] = field(default_factory=dict)


@dataclass(frozen=True)
class Model:
    """A validated, immutable model of a control program.

    Constructor inputs are copied so later caller mutation cannot affect the
    model. Expressions are validated for references and types; no input code
    is executed.
    """

    variables: Sequence[object]
    init: E.BoolExpr
    exit: E.BoolExpr
    actions: Sequence[Action]

    def __post_init__(self) -> None:
        bool_vars: Dict[str, BoolVarDecl] = {}
        int_vars: Dict[str, IntVarDecl] = {}

        if not isinstance(self.variables, (list, tuple)):
            raise ModelError("variables must be a list/tuple of declarations")
        if not self.variables:
            raise ModelError("model must declare at least one variable")
        for decl in self.variables:
            if isinstance(decl, BoolVarDecl):
                kind = "bool"
            elif isinstance(decl, IntVarDecl):
                kind = "int"
            else:
                raise ModelError(f"invalid variable declaration: {decl!r}")
            if not _id_ok(decl.name):
                raise ModelError(f"invalid variable name: {decl.name!r}")
            if decl.name in bool_vars or decl.name in int_vars:
                raise ModelError(f"duplicate variable name: {decl.name!r}")
            if kind == "bool":
                bool_vars[decl.name] = decl
            else:
                int_vars[decl.name] = decl

        if not isinstance(self.actions, (list, tuple)):
            raise ModelError("actions must be a list/tuple of Action")
        if not self.actions:
            raise ModelError("model must declare at least one action")
        names = bool_vars.keys() | int_vars.keys()
        seen_actions: set[str] = set()
        for action in self.actions:
            if not isinstance(action, Action):
                raise ModelError(f"invalid action entry: {action!r}")
            if not _id_ok(action.name):
                raise ModelError(f"invalid action name: {action.name!r}")
            if action.name in seen_actions:
                raise ModelError(f"duplicate action name: {action.name!r}")
            seen_actions.add(action.name)
            self._check_expr(action.guard, "bool", bool_vars, int_vars,
                            where=f"action {action.name!r} guard")
            if not isinstance(action.assignments, Mapping):
                raise ModelError(f"action {action.name!r}: assignments must be a mapping")
            for var_name, rhs in action.assignments.items():
                if not isinstance(var_name, str) or var_name not in names:
                    raise ModelError(
                        f"action {action.name!r}: assignment to unknown variable {var_name!r}"
                    )
                expected = "bool" if var_name in bool_vars else "int"
                self._check_expr(
                    rhs, expected, bool_vars, int_vars,
                    where=f"action {action.name!r} assignment to {var_name!r}",
                )

        for label, cond in (("init", self.init), ("exit", self.exit)):
            if isinstance(cond, bool):
                cond = E.BoolConst(cond)
                object.__setattr__(self, label, cond)
            self._check_expr(cond, "bool", bool_vars, int_vars,
                            where=f"{label} condition")

        object.__setattr__(self, "variables", tuple(self.variables))
        object.__setattr__(self, "actions", tuple(self.actions))
        for action in self.actions:
            object.__setattr__(action, "assignments", dict(action.assignments))

    @property
    def bool_vars(self) -> Dict[str, BoolVarDecl]:
        return {v.name: v for v in self.variables if isinstance(v, BoolVarDecl)}

    @property
    def int_vars(self) -> Dict[str, IntVarDecl]:
        return {v.name: v for v in self.variables if isinstance(v, IntVarDecl)}

    def with_(self, **changes) -> "Model":
        """Return a copy with replaced fields (e.g. a fixed guard)."""
        return replace(self, **changes)

    @staticmethod
    def _check_expr(node, expected, bool_vars, int_vars, *, where):
        if not isinstance(node, E.Expr):
            raise ModelError(
                f"{where}: expected structured expression node, got {node!r}"
            )
        actual = _walk_type(node, where, bool_vars, int_vars)
        if actual != expected:
            raise ModelError(
                f"{where}: expression has type {actual}, expected {expected}"
            )


def _walk_type(node, where, bool_vars, int_vars) -> str:
    if isinstance(node, E.BoolConst):
        if not isinstance(node.value, bool):
            raise ModelError(f"{where}: boolean constant must be bool")
        return "bool"
    if isinstance(node, E.IntConst):
        if isinstance(node.value, bool) or not isinstance(node.value, int):
            raise ModelError(f"{where}: integer constant must be int")
        return "int"
    if isinstance(node, E.BoolVar):
        if node.name not in bool_vars:
            hint = (
                f"unknown boolean variable {node.name!r}"
                if node.name in int_vars
                else f"unknown variable {node.name!r}"
            )
            raise ModelError(f"{where}: {hint}")
        return "bool"
    if isinstance(node, E.IntVar):
        if node.name not in int_vars:
            hint = (
                f"{node.name!r} is a boolean variable, used as integer"
                if node.name in bool_vars
                else f"unknown variable {node.name!r}"
            )
            raise ModelError(f"{where}: {hint}")
        return "int"
    if isinstance(node, (E.Add, E.Sub)):
        lt = _walk_type(node.left, where, bool_vars, int_vars)
        rt = _walk_type(node.right, where, bool_vars, int_vars)
        if lt != "int" or rt != "int":
            raise ModelError(f"{where}: arithmetic needs integer operands")
        return "int"
    if isinstance(node, E.Mul):
        if isinstance(node.k, bool) or not isinstance(node.k, int):
            raise ModelError(f"{where}: multiplication factor must be int")
        if _walk_type(node.operand, where, bool_vars, int_vars) != "int":
            raise ModelError(f"{where}: multiplication needs integer operand")
        return "int"
    if isinstance(node, E.Cmp):
        lt = _walk_type(node.left, where, bool_vars, int_vars)
        rt = _walk_type(node.right, where, bool_vars, int_vars)
        if lt != "int" or rt != "int":
            raise ModelError(f"{where}: comparison needs integer operands")
        return "bool"
    if isinstance(node, (E.And, E.Or)):
        lt = _walk_type(node.left, where, bool_vars, int_vars)
        rt = _walk_type(node.right, where, bool_vars, int_vars)
        if lt != "bool" or rt != "bool":
            raise ModelError(f"{where}: boolean operator needs bool operands")
        return "bool"
    if isinstance(node, E.Not):
        if _walk_type(node.operand, where, bool_vars, int_vars) != "bool":
            raise ModelError(f"{where}: NOT needs a boolean operand")
        return "bool"
    raise ModelError(f"{where}: unsupported expression node {type(node).__name__}")
