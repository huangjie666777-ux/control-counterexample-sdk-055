"""Symbolic encoding of model states and one-step transitions into Z3."""
from __future__ import annotations

from typing import Dict, List, Tuple

import z3

from . import expr as E
from .model import IntVarDecl, Model

__all__ = ["EncodedModel", "State", "StateEncoding"]


class State:
    """Z3 constants for one program location, plus their in-range constraints."""

    def __init__(self, encoding: "StateEncoding", step: int):
        self.step = step
        suffix = f"__s{step}"
        self.bools: Dict[str, z3.BoolRef] = {
            name: z3.Bool(name + suffix) for name in encoding.bool_names
        }
        self.ints: Dict[str, z3.ArithRef] = {
            name: z3.Int(name + suffix) for name in encoding.int_names
        }


class StateEncoding:
    def __init__(self, model: Model):
        self.model = model
        self.bool_names: List[str] = sorted(model.bool_vars)
        self.int_names: List[str] = sorted(model.int_vars)

    def fresh_state(self, step: int) -> State:
        return State(self, step)

    def bounds(self, state: State) -> List[z3.BoolRef]:
        out: List[z3.BoolRef] = []
        for name in self.int_names:
            decl: IntVarDecl = self.model.int_vars[name]
            z = state.ints[name]
            out.append(z >= decl.lower)
            out.append(z <= decl.upper)
        return out

    def to_z3(self, node: E.Expr, state: State) -> z3.ExprRef:
        return _compile(node, state)

    def enabled_guards(self, state: State):
        """Guard + RHS in-range conjuncts for each action at ``state``."""
        guards: List[z3.BoolRef] = []
        for action in self.model.actions:
            guard = _compile(action.guard, state)
            in_range: List[z3.BoolRef] = []
            for name, expr in action.assignments.items():
                value = _compile(expr, state)
                if name in self.model.int_vars:
                    decl = self.model.int_vars[name]
                    in_range.append(value >= decl.lower)
                    in_range.append(value <= decl.upper)
            guards.append(z3.And([guard, *in_range]))
        return guards

    def transition(self, src: State, dst: State) -> Tuple[
        List[z3.BoolRef], List[z3.BoolRef], List[z3.BoolRef], z3.BoolRef
    ]:
        """Return (action_guards, branch_formulas).

        Exactly one enabled action fires. Each branch formula is the
        conjunction of: this action is enabled (guard and all RHS values in
        range), and the destination is exactly the simultaneous update of
        src with unassigned variables keeping their values.
        """
        guards: List[z3.BoolRef] = []
        branches: List[z3.BoolRef] = []
        chosen = []
        for action in self.model.actions:
            choose = z3.FreshBool(f"fire_{action.name}__{src.step}_")
            guard = _compile(action.guard, src)
            rhs = {name: _compile(ex, src) for name, ex in action.assignments.items()}
            in_range: List[z3.BoolRef] = []
            for name, value in rhs.items():
                if name in self.model.int_vars:
                    decl = self.model.int_vars[name]
                    in_range.append(value >= decl.lower)
                    in_range.append(value <= decl.upper)
            enabled = z3.And([choose, guard, *in_range])
            eq_parts: List[z3.BoolRef] = []
            frame_parts: List[z3.BoolRef] = []
            for name in self.bool_names:
                new_val = rhs.get(name)
                if new_val is None:
                    frame_parts.append(dst.bools[name] == src.bools[name])
                else:
                    eq_parts.append(dst.bools[name] == new_val)
            for name in self.int_names:
                new_val = rhs.get(name)
                if new_val is None:
                    frame_parts.append(dst.ints[name] == src.ints[name])
                else:
                    eq_parts.append(dst.ints[name] == new_val)
            guards.append(enabled)
            branches.append(z3.And([enabled, *eq_parts, *frame_parts]))
            chosen.append(choose)
        exactly_one = z3.PbEq([(z, 1) for z in chosen], 1)
        return guards, branches, chosen, exactly_one


class EncodedModel:
    """Reusable symbolic view of a validated Model."""

    def __init__(self, model: Model):
        self.model = model
        self.encoding = StateEncoding(model)

    def states(self, count: int) -> List[State]:
        return [self.encoding.fresh_state(i) for i in range(count)]

    def init_constraints(self, state: State) -> List[z3.BoolRef]:
        return [*self.encoding.bounds(state), _compile(self.model.init, state)]

    def exit_expr(self, state: State) -> z3.BoolRef:
        return _compile(self.model.exit, state)

    def safety_expr(self, condition: E.BoolExpr, state: State) -> z3.BoolRef:
        return _compile(condition, state)

    def step(self, src: State, dst: State):
        return self.encoding.transition(src, dst)

    def enabled_guards(self, state: State):
        return self.encoding.enabled_guards(state)


def _compile(node: E.Expr, state: State) -> z3.ExprRef:
    if isinstance(node, E.BoolConst):
        return z3.BoolVal(node.value)
    if isinstance(node, E.IntConst):
        return z3.IntVal(node.value)
    if isinstance(node, E.BoolVar):
        return state.bools[node.name]
    if isinstance(node, E.IntVar):
        return state.ints[node.name]
    if isinstance(node, E.Add):
        return _compile(node.left, state) + _compile(node.right, state)
    if isinstance(node, E.Sub):
        return _compile(node.left, state) - _compile(node.right, state)
    if isinstance(node, E.Mul):
        return _compile(node.operand, state) * node.k
    if isinstance(node, E.Cmp):
        left = _compile(node.left, state)
        right = _compile(node.right, state)
        ops = {
            "eq": lambda a, b: a == b,
            "ne": lambda a, b: a != b,
            "lt": lambda a, b: a < b,
            "le": lambda a, b: a <= b,
            "gt": lambda a, b: a > b,
            "ge": lambda a, b: a >= b,
        }
        return ops[node.op](left, right)
    if isinstance(node, E.And):
        return z3.And(_compile(node.left, state), _compile(node.right, state))
    if isinstance(node, E.Or):
        return z3.Or(_compile(node.left, state), _compile(node.right, state))
    if isinstance(node, E.Not):
        return z3.Not(_compile(node.operand, state))
    raise TypeError(f"unsupported expression node: {type(node).__name__}")
