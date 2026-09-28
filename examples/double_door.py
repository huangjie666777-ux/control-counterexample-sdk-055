"""Double-door airlock interlock demo.

Two doors guard a chamber that must never be open to both sides at
once: the safety property is "not (door1_open and door2_open)".

The flawed controller lets each door open regardless of the other door,
so both doors can be open simultaneously. The fixed controller guards
the open actions on the other door being closed.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from controlcheck import (  # noqa: E402
    Action,
    And,
    Cmp,
    Const,
    COUNTEREXAMPLE,
    Model,
    Not,
    Var,
    check_safety,
    verify_counterexample,
)


def build_flawed() -> Model:
    d1, d2 = Var("door1_open"), Var("door2_open")
    return Model(
        bool_vars=("door1_open", "door2_open"),
        int_vars={},
        init=And(Not(d1), Not(d2)),
        terminal=Const(False),
        actions=(
            Action("open_door1", Not(d1), {"door1_open": Const(True)}),
            Action("close_door1", d1, {"door1_open": Const(False)}),
            Action("open_door2", Not(d2), {"door2_open": Const(True)}),
            Action("close_door2", d2, {"door2_open": Const(False)}),
        ),
    )


def build_fixed() -> Model:
    d1, d2 = Var("door1_open"), Var("door2_open")
    return Model(
        bool_vars=("door1_open", "door2_open"),
        int_vars={},
        init=And(Not(d1), Not(d2)),
        terminal=Const(False),
        actions=(
            Action("open_door1", And(Not(d1), Not(d2)), {"door1_open": Const(True)}),
            Action("close_door1", d1, {"door1_open": Const(False)}),
            Action("open_door2", And(Not(d2), Not(d1)), {"door2_open": Const(True)}),
            Action("close_door2", d2, {"door2_open": Const(False)}),
        ),
    )


def both_closed_safety() -> Cmp:
    return Not(And(Var("door1_open"), Var("door2_open")))


def show(title: str, model: Model, bound: int = 4) -> None:
    print(f"=== {title} ===")
    result = check_safety(model, bound, both_closed_safety())
    if result.status == COUNTEREXAMPLE:
        cex = result.counterexample
        print(f"counterexample in {cex.length} step(s), reason: {cex.reason}")
        for i, (state, action) in enumerate(zip(cex.states, cex.actions)):
            print(f"  state {i}: {state}  --{action}-->")
        print(f"  state {len(cex.states) - 1}: {cex.states[-1]}  FAILURE")
        trace = verify_counterexample(model, result, both_closed_safety())
        print(f"  concrete replay verified {len(trace.states)} states OK")
    else:
        print(f"status: {result.status} (bound={bound}); no claim of global safety")
    print()


if __name__ == "__main__":
    show("flawed double-door interlock", build_flawed())
    show("fixed double-door interlock", build_fixed())
