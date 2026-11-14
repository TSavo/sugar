from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.floor import SymbolicValue, TermValue
from sugar_lift_py_tests.ir import ctor, not_
from sugar_lift_py_tests.outcome.exit_set import Completed, ExitSet, Halted, true_guard
from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock
from sugar_lift_py_tests.sugar.if_sugar import predicate_formula

# The record the body left before the exit: the one shape a halt's state takes.
_BEFORE_EXIT = _ReducedBlock((TermValue("before-exit"),), True, ())


def test_source_constructed_exit_retains_suppressed_and_unsuppressed_faces():
    original = RaiseEffect.for_builtin("ValueError", blame="boom", occurrence="boom")
    incoming = ExitSet.halted(original, state=_BEFORE_EXIT)
    result = SymbolicValue(ctor("fixture:exit-result", []))

    routed = incoming.and_exit_truthiness(
        ExitSet.completed(result), site="renamed-fixture"
    )

    truth = predicate_formula(result, "renamed-fixture")
    assert routed.exits == (
        Completed(truth, _BEFORE_EXIT),
        Halted(not_(truth), original, _BEFORE_EXIT),
    )


def test_source_constructed_false_exit_restores_original_effect():
    original = RaiseEffect.for_builtin("ValueError", blame="boom", occurrence="boom")
    incoming = ExitSet.halted(original, state=_BEFORE_EXIT)

    routed = incoming.and_exit_truthiness(
        ExitSet.completed(TermValue(False)), site="renamed-fixture"
    )

    assert routed.exits == (Halted(true_guard(), original, _BEFORE_EXIT),)


def test_source_constructed_exit_runs_on_non_exception_transfer():
    body_result = TermValue("return-break-or-continue")
    incoming = ExitSet.completed(body_result)

    routed = incoming.and_exit_truthiness(
        ExitSet.completed(TermValue(True)), site="renamed-fixture"
    )

    assert routed.exits == (Completed(true_guard(), body_result),)
