import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from controlcheck import (
    Action,
    Add,
    And,
    COUNTEREXAMPLE,
    Const,
    Cmp,
    DEADLOCK,
    INIT_UNSAT,
    Mul,
    Model,
    ModelError,
    NO_COUNTEREXAMPLE_IN_BOUND,
    Not,
    Or,
    ReplayError,
    Sub,
    UNKNOWN,
    Var,
    check_deadlock,
    check_safety,
    replay_sequence,
    verify_counterexample,
)


def safety_not_both():
    return Not(And(Var("door1_open"), Var("door2_open")))


def door_model():
    d1, d2 = Var("door1_open"), Var("door2_open")
    return Model(
        bool_vars=("door1_open", "door2_open"),
        int_vars={},
        init=And(Not(d1), Not(d2)),
        terminal=Const(False),
        actions=(
            Action("open1", Not(d1), {"door1_open": Const(True)}),
            Action("close1", d1, {"door1_open": Const(False)}),
            Action("open2", Not(d2), {"door2_open": Const(True)}),
            Action("close2", d2, {"door2_open": Const(False)}),
        ),
    )


class TestValidation(unittest.TestCase):
    def test_unknown_variable_reference(self):
        with self.assertRaises(ModelError):
            Model(("a"), {}, Const(True), Const(False),
                  (Action("x", Var("missing"), {}),))

    def test_type_mismatch_guard(self):
        with self.assertRaises(ModelError):
            Model((), {"x": (0, 1)}, Const(True), Const(False),
                  (Action("x", Var("x"), {}),))

    def test_type_mismatch_assignment(self):
        with self.assertRaises(ModelError):
            Model(("b",), {"x": (0, 1)}, Const(True), Const(False),
                  (Action("x", Const(True), {"b": Const(1)}),))

    def test_duplicate_action_names(self):
        with self.assertRaises(ModelError):
            Model(("b",), {}, Const(True), Const(False),
                  (Action("x", Const(True), {"b": Const(True)}),
                   Action("x", Const(True), {"b": Const(False)})))

    def test_duplicate_variable_and_empty_domain(self):
        with self.assertRaises(ModelError):
            Model(("b",), {"b": (0, 1)}, Const(True), Const(False), ())
        with self.assertRaises(ModelError):
            Model((), {"x": (2, 1)}, Const(True), Const(False), ())

    def test_arithmetic_requires_ints(self):
        with self.assertRaises(ModelError):
            Model(("b",), {}, Const(True), Const(False),
                  (Action("x", Cmp("<", Add(Var("b"), Const(1)), Const(2)), {}),))

    def test_bound_must_be_nonnegative_int(self):
        with self.assertRaises(ModelError):
            check_safety(door_model(), -1, safety_not_both())


class TestSafety(unittest.TestCase):
    def test_shortest_door_violation_and_replay(self):
        model = door_model()
        result = check_safety(model, 4, safety_not_both())
        self.assertEqual(result.status, COUNTEREXAMPLE)
        cex = result.counterexample
        self.assertEqual(cex.length, 2)
        self.assertIn(cex.actions, [["open1", "open2"], ["open2", "open1"]])
        trace = verify_counterexample(model, result, safety_not_both())
        self.assertEqual(trace.reason, "safety_violated")

    def test_initial_state_included_bound_zero(self):
        m = Model(("a",), {}, Var("a"), Const(False),
                  (Action("f", Const(True), {"a": Const(False)}),))
        result = check_safety(m, 0, Not(Var("a")))
        self.assertEqual(result.status, COUNTEREXAMPLE)
        self.assertEqual(result.counterexample.length, 0)

    def test_fixed_interlock_clean(self):
        d1, d2 = Var("door1_open"), Var("door2_open")
        fixed = Model(
            bool_vars=("door1_open", "door2_open"),
            int_vars={},
            init=And(Not(d1), Not(d2)),
            terminal=Const(False),
            actions=(
                Action("open1", And(Not(d1), Not(d2)), {"door1_open": Const(True)}),
                Action("close1", d1, {"door1_open": Const(False)}),
                Action("open2", And(Not(d2), Not(d1)), {"door2_open": Const(True)}),
                Action("close2", d2, {"door2_open": Const(False)}),
            ),
        )
        result = check_safety(fixed, 5, safety_not_both())
        self.assertEqual(result.status, NO_COUNTEREXAMPLE_IN_BOUND)
        self.assertIsNone(result.counterexample)
        self.assertTrue(result.ok_within_bound)

    def test_init_unsat_reported_separately(self):
        m = Model(("a",), {}, And(Var("a"), Not(Var("a"))), Const(False),
                  (Action("f", Const(True), {"a": Const(False)}),))
        self.assertEqual(check_safety(m, 3, Const(True)).status, INIT_UNSAT)
        self.assertEqual(check_deadlock(m, 3).status, INIT_UNSAT)


class TestTransitions(unittest.TestCase):
    def _counter_model(self):
        return Model(
            bool_vars=(),
            int_vars={"x": (0, 3)},
            init=Cmp("==", Var("x"), Const(0)),
            terminal=Const(False),
            actions=(
                Action("inc", Cmp("<", Var("x"), Const(3)),
                       {"x": Add(Var("x"), Const(1))}),
                Action("big", Const(True), {"x": Add(Var("x"), Const(5))}),
            ),
        )

    def test_out_of_bounds_action_not_executable_and_deadlock(self):
        model = self._counter_model()
        # x in [0,3]: 'inc' reaches 3 and is then disabled; 'big' always
        # overflows, so x==3 is a non-terminal deadlock.
        result = check_deadlock(model, 4)
        self.assertEqual(result.status, COUNTEREXAMPLE)
        self.assertEqual(result.counterexample.reason, DEADLOCK)
        self.assertEqual(result.counterexample.states[-1]["x"], 3)

    def test_branching_does_not_choose_out_of_bounds_action(self):
        model = self._counter_model()
        result = check_safety(model, 3, Cmp("<=", Var("x"), Const(3)))
        self.assertEqual(result.status, NO_COUNTEREXAMPLE_IN_BOUND)

    def test_simultaneous_assignment_reads_old_state(self):
        m = Model(
            bool_vars=(),
            int_vars={"x": (0, 10), "y": (0, 10)},
            init=And(Cmp("==", Var("x"), Const(1)), Cmp("==", Var("y"), Const(2))),
            terminal=Const(False),
            actions=(
                Action("swap", Const(True),
                       {"x": Var("y"), "y": Var("x")}),
            ),
        )
        states = replay_sequence(m, {"x": 1, "y": 2}, ["swap"])
        self.assertEqual(states[-1], {"x": 2, "y": 1})
        result = check_safety(m, 1, And(
            Cmp("==", Var("x"), Const(2)), Cmp("==", Var("y"), Const(1))))
        self.assertEqual(result.status, COUNTEREXAMPLE)
        verify_counterexample(m, result, And(
            Cmp("==", Var("x"), Const(2)), Cmp("==", Var("y"), Const(1))))

    def test_unassigned_variables_persist(self):
        m = Model(
            bool_vars=("b",),
            int_vars={"x": (0, 5)},
            init=And(Var("b"), Cmp("==", Var("x"), Const(4))),
            terminal=Const(False),
            actions=(Action("flip", Const(True), {"b": Const(False)}),),
        )
        result = check_safety(m, 1, Cmp("==", Var("x"), Const(4)))
        self.assertEqual(result.status, NO_COUNTEREXAMPLE_IN_BOUND)

    def test_all_init_states_participate(self):
        # init leaves x free in [0,2]; property x>=1 fails at x=0.
        m = Model(
            (), {"x": (0, 2)}, Const(True), Const(False),
            (Action("inc", Cmp("<", Var("x"), Const(2)),
                    {"x": Add(Var("x"), Const(1))}),),
        )
        result = check_safety(m, 0, Cmp(">=", Var("x"), Const(1)))
        self.assertEqual(result.status, COUNTEREXAMPLE)
        self.assertEqual(result.counterexample.states[0]["x"], 0)


class TestIsolation(unittest.TestCase):
    def test_checks_do_not_mutate_model_and_replay_catches_bad_trace(self):
        model = door_model()
        check_safety(model, 3, safety_not_both())
        check_deadlock(model, 3)
        self.assertEqual(len(model.actions), 4)
        states = replay_sequence(model,
                                 {"door1_open": False, "door2_open": False},
                                 ["open1"])
        self.assertEqual(states[-1], {"door1_open": True, "door2_open": False})
        with self.assertRaises(ReplayError):
            replay_sequence(model, {"door1_open": True, "door2_open": False},
                            ["open1"])


if __name__ == "__main__":
    unittest.main()
