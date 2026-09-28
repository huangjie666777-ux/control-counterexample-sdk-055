"""Z3 symbolic encoding of a validated model.

The transition relation is unrolled symbolically: variables at each step
are Z3 constants, guards and right-hand sides read the old step, and all
assignments of the chosen action update simultaneously. An action is
executable only when its guard holds and every assigned integer stays
within its declared bounds. Unassigned variables keep their old values.
Exactly one action is taken per step; no implicit stuttering is added.
"""

from __future__ import annotations

from typing import Dict, List

import z3

from .expressions import Add, And, Cmp, Const, Mul, Not, Or, Sub, Var
from .model import Action, Model


def encode_expr(expr, ctx: Dict[str, z3.ExprRef]):
    if isinstance(expr, Var):
        return ctx[expr.name]
    if isinstance(expr, Const):
        return z3.BoolVal(expr.value) if isinstance(expr.value, bool) else z3.IntVal(expr.value)
    if isinstance(expr, Add):
        return encode_expr(expr.left, ctx) + encode_expr(expr.right, ctx)
    if isinstance(expr, Sub):
        return encode_expr(expr.left, ctx) - encode_expr(expr.right, ctx)
    if isinstance(expr, Mul):
        return expr.coef * encode_expr(expr.expr, ctx)
    if isinstance(expr, Cmp):
        lhs, rhs = encode_expr(expr.left, ctx), encode_expr(expr.right, ctx)
        return {
            "==": lhs == rhs,
            "!=": lhs != rhs,
            "<": lhs < rhs,
            "<=": lhs <= rhs,
            ">": lhs > rhs,
            ">=": lhs >= rhs,
        }[expr.op]
    if isinstance(expr, And):
        return z3.And(*[encode_expr(a, ctx) for a in expr.args])
    if isinstance(expr, Or):
        return z3.Or(*[encode_expr(a, ctx) for a in expr.args])
    if isinstance(expr, Not):
        return z3.Not(encode_expr(expr.arg, ctx))
    raise TypeError(f"cannot encode {expr!r}")


class StepEncoder:
    """Encodes one bounded unrolling of a model into a solver."""

    def __init__(self, model: Model):
        self.model = model
        self.names: List[str] = list(model.bool_vars) + list(model.int_vars)

    def state_vars(self, step: int) -> Dict[str, z3.ExprRef]:
        ctx: Dict[str, z3.ExprRef] = {}
        for name in self.model.bool_vars:
            ctx[name] = z3.Bool(f"{name}@{step}")
        for name in self.model.int_vars:
            ctx[name] = z3.Int(f"{name}@{step}")
        return ctx

    def domain_constraints(self, ctx: Dict[str, z3.ExprRef]) -> List[z3.BoolRef]:
        return [
            z3.And(lo <= ctx[name], ctx[name] <= hi)
            for name, (lo, hi) in self.model.int_vars.items()
        ]

    def action_executable(self, action: Action, ctx: Dict[str, z3.ExprRef]) -> z3.BoolRef:
        """Guard holds and every assigned integer value stays in bounds."""
        conds = [encode_expr(action.guard, ctx)]
        for target, rhs in action.assigns.items():
            if target in self.model.int_vars:
                lo, hi = self.model.int_vars[target]
                val = encode_expr(rhs, ctx)
                conds += [lo <= val, val <= hi]
        return z3.And(*conds)

    def transition(self, step: int, pre: Dict[str, z3.ExprRef], post: Dict[str, z3.ExprRef]):
        """Returns (constraint, action_selectors) for exactly one action firing."""
        selectors = []
        branches = []
        for idx, action in enumerate(self.model.actions):
            sel = z3.Bool(f"act@{step}@{idx}")
            selectors.append(sel)
            effects = []
            for name in self.names:
                if name in action.assigns:
                    effects.append(post[name] == encode_expr(action.assigns[name], pre))
                else:
                    effects.append(post[name] == pre[name])
            branches.append(z3.And(sel, self.action_executable(action, pre), *effects))
        exactly_one = z3.PbEq([(s, 1) for s in selectors], 1) if selectors else z3.BoolVal(False)
        return z3.And(z3.Or(*branches), exactly_one), selectors

    def deadlock_at(self, ctx: Dict[str, z3.ExprRef]) -> z3.BoolRef:
        """Non-terminal state with no executable action."""
        no_action = z3.And(
            *[z3.Not(self.action_executable(a, ctx)) for a in self.model.actions]
        ) if self.model.actions else z3.BoolVal(True)
        return z3.And(z3.Not(encode_expr(self.model.terminal, ctx)), no_action)


def decode_state(z3model: z3.ModelRef, ctx: Dict[str, z3.ExprRef]) -> Dict[str, object]:
    state: Dict[str, object] = {}
    for name, ref in ctx.items():
        value = z3model.eval(ref, model_completion=True)
        state[name] = bool(z3.is_true(value)) if z3.is_bool(ref) else value.as_long()
    return state
