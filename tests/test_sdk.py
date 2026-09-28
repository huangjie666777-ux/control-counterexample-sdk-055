import unittest

import z3

from controlcheck import (
    Action,
    BoolVarDecl,
    CheckKind,
    CheckStatus,
    IntVarDecl,
    Model,
    ModelError,
    c,
    check_deadlock,
    check_safety,
    eq,
    gt,
    le,
    lt,
    var,
    verify_counterexample,
)
from controlcheck.expr import BoolVar, IntVar
from controlcheck.replay import action_is_enabled, evaluate


def double_door(*, buggy: bool):
    a = BoolVar("door_a")
    b = BoolVar("door_b")
    actions = [
        Action("open_a", guard=~b,
               assignments={"door_a": c(True)}),
        Action("open_b", guard=(~a if not buggy else c(True)),
               assignments={"door_b": c(True)}),
        Action(
            "close_a",
            guard=a if buggy else a & ~b,
            assignments={"door_a": c(False)},
        ),
        Action("close_b", guard=b & ~a, assignments={"door_b": c(False)}),
    ]
    return Model(
        variables=[BoolVarDecl("door_a"), BoolVarDecl("door_b")],
        init=(~a) & (~b),
        exit=(~a) & (~b),
        actions=actions,
    )


SAFETY = ~(BoolVar("door_a") & BoolVar("door_b"))


class ModelValidationTests(unittest.TestCase):
    def test_duplicate_action_rejected(self):
        m = double_door(buggy=True)
        dup = Action("open_a", guard=~BoolVar("door_b"),
                     assignments={"door_a": c(True)})
        with self.assertRaises(ModelError):
            Model(m.variables, m.init, m.exit, [*m.actions, dup])

    def test_unknown_reference_and_type_errors(self):
        a = BoolVar("door_a")
        with self.assertRaises(ModelError):
            Model([BoolVarDecl("door_a")], init=a, exit=a,
                  actions=[Action("step", guard=a, assignments={"nope": c(True)})])
        with self.assertRaises(ModelError):
            Model([BoolVarDecl("door_a")], init=a, exit=a,
                  actions=[Action("step", guard=eq(IntVar("x"), 0))])
        with self.assertRaises(ModelError):
            Model([BoolVarDecl("door_a"), IntVarDecl("x", 0, 1)], init=a, exit=a,
                  actions=[Action("step", guard=a, assignments={"door_a": c(1)})])

    def test_integer_bounds_and_structure(self):
        with self.assertRaises(ModelError):
            IntVarDecl("x", 2, 1)
        x = IntVar("x")
        with self.assertRaises(TypeError):
            _ = x * x  # non-constant multiplication is not part of the language

    def test_non_expression_rejected(self):
        with self.assertRaises(ModelError):
            Model([BoolVarDecl("a")], init=BoolVar("a"), exit=BoolVar("a"),
                  actions=[Action("s", guard=lambda s: True)])

class DoubleDoorTests(unittest.TestCase):
    def test_buggy_interlock_has_two_step_violation(self):
        result = check_safety(double_door(buggy=True), SAFETY, bound=5)
        self.assertEqual(result.status, CheckStatus.COUNTEREXAMPLE)
        cex = result.counterexample
        self.assertEqual(cex.length, 2)
        self.assertEqual(
            [s.action for s in cex.steps if s.action is not None],
            ["open_a", "open_b"],
        )
        self.assertTrue(cex.final_state["door_a"])
        self.assertTrue(cex.final_state["door_b"])
        replayed = verify_counterexample(double_door(buggy=True), cex, SAFETY)
        self.assertTrue(replayed.ok, replayed.errors)

    def test_fixed_interlock_clean_within_bound(self):
        result = check_safety(double_door(buggy=False), SAFETY, bound=5)
        self.assertEqual(result.status, CheckStatus.NO_COUNTEREXAMPLE_IN_BOUND)
        self.assertIsNone(result.counterexample)
        self.assertIn("5 step(s)", result.reason)

    def test_fixed_model_no_deadlock(self):
        result = check_deadlock(double_door(buggy=False), bound=5)
        self.assertEqual(result.status, CheckStatus.NO_COUNTEREXAMPLE_IN_BOUND)


class SemanticsTests(unittest.TestCase):
    def counter_model(self):
        n = IntVar("n")
        return Model(
            variables=[BoolVarDecl("run"), IntVarDecl("n", 0, 3)],
            init=(~BoolVar("run")) & (eq(n, 0)),
            exit=(~BoolVar("run")) & (eq(n, 0)),
            actions=[
                Action("inc", guard=BoolVar("run") & (lt(n, 3)),
                       assignments={"n": n + 1}),
                Action("start", guard=~BoolVar("run"),
                       assignments={"run": c(True)}),
                Action("stop", guard=BoolVar("run"),
                       assignments={"run": c(False)}),
            ],
        )

    def test_out_of_range_update_disables_action(self):
        m = self.counter_model()
        state = {"run": True, "n": 3}
        self.assertFalse(action_is_enabled(m, m.actions[0], state))
        self.assertTrue(action_is_enabled(m, m.actions[2], state))

    def test_simultaneous_update_reads_old_state(self):
        x = IntVar("x")
        y = IntVar("y")
        m = Model(
            variables=[IntVarDecl("x", 0, 5), IntVarDecl("y", 0, 5)],
            init=(eq(x, 1)) & (eq(y, 2)),
            exit=(eq(x, 0)) & (eq(y, 0)),
            actions=[Action("swap", guard=c(True),
                            assignments={"x": y, "y": x})],
        )
        result = check_safety(m, le(y, 1), bound=1)
        self.assertEqual(result.status, CheckStatus.COUNTEREXAMPLE)
        cex = result.counterexample
        self.assertEqual(cex.length, 0)
        replayed = verify_counterexample(m, cex, le(y, 1))
        self.assertTrue(replayed.ok, replayed.errors)

    def test_initial_state_zero_step_included_for_safety(self):
        x = IntVar("x")
        m = Model(
            variables=[IntVarDecl("x", 0, 2)],
            init=eq(x, 0),
            exit=c(False),
            actions=[Action("idle", guard=c(True), assignments={"x": x})],
        )
        result = check_safety(m, gt(x, 0), bound=3)
        self.assertEqual(result.status, CheckStatus.COUNTEREXAMPLE)
        self.assertEqual(result.counterexample.length, 0)
        self.assertTrue(verify_counterexample(m, result.counterexample, gt(x, 0)).ok)

    def test_init_unsat_reported_separately(self):
        x = IntVar("x")
        m = Model(
            variables=[IntVarDecl("x", 0, 2)],
            init=(x < 0) & (x > 1),
            exit=c(False),
            actions=[Action("idle", guard=c(True), assignments={"x": x})],
        )
        result = check_safety(m, eq(x, 0), bound=3)
        self.assertEqual(result.status, CheckStatus.INIT_UNSAT)
        self.assertIsNone(result.counterexample)

    def test_invalid_bound(self):
        m = double_door(buggy=False)
        result = check_safety(m, SAFETY, -1)
        self.assertEqual(result.status, CheckStatus.INVALID_BOUND)

    def test_checks_do_not_pollute_each_other(self):
        m = double_door(buggy=True)
        first = check_safety(m, SAFETY, bound=1)
        second = check_safety(m, SAFETY, bound=5)
        self.assertEqual(first.status, CheckStatus.NO_COUNTEREXAMPLE_IN_BOUND)
        self.assertEqual(second.status, CheckStatus.COUNTEREXAMPLE)
        third = check_safety(m, SAFETY, bound=5)
        self.assertEqual(third.counterexample.length, 2)

    def test_deadlock_detection_on_locked_counter(self):
        n = IntVar("n")
        m = Model(
            variables=[BoolVarDecl("run"), IntVarDecl("n", 0, 3)],
            init=BoolVar("run") & (eq(n, 3)),
            exit=~BoolVar("run"),
            actions=[
                Action("inc", guard=BoolVar("run") & (lt(n, 3)),
                       assignments={"n": n + 1}),
            ],
        )
        result = check_deadlock(m, bound=0)
        self.assertEqual(result.status, CheckStatus.COUNTEREXAMPLE)
        self.assertEqual(result.counterexample.kind, CheckKind.DEADLOCK)
        self.assertIn("no legal enabled action",
                      result.counterexample.failure_reason)
        self.assertTrue(verify_counterexample(m, result.counterexample).ok)

    def test_constant_multiplication_supported(self):
        x = IntVar("x")
        m = Model(
            variables=[IntVarDecl("x", 0, 10)],
            init=eq(x, 2),
            exit=c(False),
            actions=[Action("double", guard=le(2 * x, 10),
                           assignments={"x": 2 * x})],
        )
        result = check_safety(m, lt(x, 4), bound=1)
        self.assertEqual(result.status, CheckStatus.COUNTEREXAMPLE)
        self.assertEqual(result.counterexample.final_state["x"], 4)


if __name__ == "__main__":
    unittest.main()
