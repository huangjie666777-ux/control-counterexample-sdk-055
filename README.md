# Control Counterexample SDK

+# Control Counterexample SDK

Bounded model checking for industrial control logic. Before connecting real
equipment, the SDK symbolically searches action paths that either:

- violate a boolean **safety/interlock condition**, or
- **deadlock** a non-terminal state (no legal successor action).

The engine uses Z3 to unroll the transition relation symbolically; it never
enumerates concrete variable assignments to pretend it is solving. Every check is
bounded by a caller-supplied step limit and returns the *shortest* witness.

## Installation

Python 3.10 and Z3 4.13.4 are pinned in requirements.txt:

    .venv/bin/pip install -e .

Use the project interpreter directly: .venv/bin/python

## Modeling

Models contain named boolean variables, bounded integer variables, an initial
condition, a terminal (exit) condition, and uniquely named actions. Each action
has a boolean guard and simultaneous variable assignments:

    from controlcheck import (
        Action, BoolVar, BoolVarDecl, IntVarDecl, IntVar, Model, c, eq, lt,
    )

    n = IntVar("n")
    model = Model(
        variables=[BoolVarDecl("run"), IntVarDecl("n", lower=0, upper=3)],
        init=(~BoolVar("run")) & eq(n, 0),
        exit=~BoolVar("run"),
        actions=[
            Action("start", guard=~BoolVar("run"),
                   assignments={"run": c(True)}),
            Action("inc", guard=BoolVar("run") & lt(n, 3),
                   assignments={"n": n + 1}),
            Action("stop", guard=BoolVar("run"),
                   assignments={"run": c(False)}),
        ],
    )

Expressions are declarative AST nodes (no eval/exec of caller input):

- variables: BoolVar/IntVar, constants: c(True), c(3)
- integers: x + y, x - 1, 2 * x (multiplication by a constant only)
- comparisons: eq/ne/lt/le/gt/ge (operator overloads work on expression nodes,
  but comparisons with raw Python ints on the left can be shadowed by Python's
  int; use the explicit constructors for robust models)
- booleans: a & b, a | b, ~a

Model construction validates:

- name uniqueness and identifiers for variables/actions
- variable references (unknown names are rejected)
- expression types (boolean vs integer)
- integer bounds consistency
- structural validity (guards must be boolean, RHS must match variable type)

Invalid models raise controlcheck.ModelError with a precise message.

## Transition semantics

At each step exactly one enabled action is chosen.

- An action is enabled when its guard is true and every assigned integer RHS
  stays inside the declared bounds.
- The guard and all assignment right-hand sides read the OLD state.
- All assignments apply simultaneously; unassigned variables keep their value.
- When several actions are enabled, each is a possible branch.
- No implicit wait/idle action is added.
- All legal states satisfying init participate; if init has no solution the
  result status is init_unsat.

## Running checks

    from controlcheck import check_safety, check_deadlock, CheckStatus

    result = check_safety(model, safety=~(BoolVar("door_a") & BoolVar("door_b")),
                          bound=10, timeout_ms=5000)
    # or
    result = check_deadlock(model, bound=10)

Safety checks include the initial state (length-0 witnesses are possible).
Deadlock means: state is reachable, exit is false there, and no action is
enabled. Each length is solved independently from 0..bound, so the returned
counterexample is shortest.

Result statuses (result.status):

- counterexample: result.counterexample holds the witness
- no_counterexample_in_bound: scoped statement only; global safety is never
  claimed
- init_unsat: no legal initial state exists
- timeout: Z3 hit timeout_ms (reported distinctly from unknown)
- unknown: Z3 returned unknown for another reason
- invalid_bound: bound was not a non-negative integer

## Counterexamples and replay

A counterexample contains every complete state (all variables), the action name
between states, the witness length and a terminal failure reason. Verify it
independently with a concrete (non-Z3) semantic replay:

    from controlcheck import verify_counterexample

    replay_result = verify_counterexample(model, result.counterexample, safety)
    assert replay_result.ok, replay_result.errors

The replay re-checks init, bounds, every guard, simultaneous updates and the
terminal failure, and compares each replayed state against the reported witness.

Checks never mutate or alias the caller's model (inputs are copied/revalidated),
and each check builds fresh Z3 constants/solvers, so repeated calls cannot
pollute one another.

## Demo and tests

    .venv/bin/python examples/double_door_demo.py
    PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v

The demo models a double-door airlock: a defective open_b action missing the
"door A must be closed" interlock produces a 2-step both-doors-open path, and
the repaired model passes both safety and deadlock bounded checks.
