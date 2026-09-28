"""End-to-end demo: double-door airlock interlock, defective vs fixed.

Run with: .venv/bin/python examples/double_door_demo.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from controlcheck import (  # noqa: E402
    Action,
    BoolVar,
    BoolVarDecl,
    CheckStatus,
    IntVarDecl,
    Model,
    c,
    check_deadlock,
    check_safety,
    verify_counterexample,
)

A = BoolVar("door_a")
B = BoolVar("door_b")
SAFETY = ~(A & B)
BOUND = 6


def build_airlock(*, buggy: bool) -> Model:
    # In the fixed logic opening B requires A to be closed; the defective
    # build drops that check on open_b.
    open_b_guard = ~A if not buggy else c(True)
    return Model(
        variables=[BoolVarDecl("door_a"), BoolVarDecl("door_b")],
        init=(~A) & (~B),
        exit=(~A) & (~B),
        actions=[
            Action("open_a", guard=~B, assignments={"door_a": c(True)}),
            Action("open_b", guard=open_b_guard,
                   assignments={"door_b": c(True)}),
            Action("close_a", guard=A & ~B,
                   assignments={"door_a": c(False)}),
            Action("close_b", guard=B & ~A,
                   assignments={"door_b": c(False)}),
        ],
    )


def show(title: str, result) -> None:
    print("=" * 64)
    print(title)
    print("-" * 64)
    print("status:", result.status.value)
    if result.status is CheckStatus.COUNTEREXAMPLE:
        cex = result.counterexample
        print("shortest counterexample length:", cex.length, "step(s)")
        print("state 0:", cex.steps[0].state, "(initial)")
        for step in cex.steps[1:]:
            print(f"  --[{step.action}]--> state {step.index}: {step.state}")
        print("  ^ FAILURE: safety condition is false at final state")
        print("failure:", cex.failure_reason)
    else:
        print("result:", result.reason)
    print()


def main() -> None:
    buggy = build_airlock(buggy=True)
    fixed = build_airlock(buggy=False)

    result = check_safety(buggy, SAFETY, bound=BOUND)
    show("1) DEFECTIVE logic, bounded safety check", result)
    if result.counterexample is not None:
        replay_result = verify_counterexample(buggy, result.counterexample, SAFETY)
        print("independent concrete replay ok:", replay_result.ok)
        if replay_result.errors:
            print("replay errors:", replay_result.errors)
        print()

    show("2) FIXED logic, bounded safety check",
         check_safety(fixed, SAFETY, bound=BOUND))
    show("3) FIXED logic, bounded deadlock check",
         check_deadlock(fixed, bound=BOUND))


if __name__ == "__main__":
    main()
