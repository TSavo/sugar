from sugar_lift_python_source.canonical import blake3_512_of

from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import SymbolicValue, TermValue
from sugar_lift_py_tests.floor.predicate_value import PredicateValue
from sugar_lift_py_tests.ir import atomic, ctor, not_
from sugar_lift_py_tests.outcome.exit_set import Completed, ExitSet, Halted, true_guard
from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock
from sugar_lift_py_tests.sugar.if_sugar import predicate_formula

# The record the body left before the exit: the one shape a halt's state takes.
_BEFORE_EXIT = _ReducedBlock((TermValue("before-exit"),), True, ())


class _ExitSite:
    """A source fragment's coordinate: an undecided truth keys its faces on
    the operation's occurrence (``occurrence.occurrence_key``)."""

    class _Span:
        start_line, start_col, end_line, end_col = 4, 4, 4, 20

    source_cid = blake3_512_of(b"exit-truthiness")
    line_col_span = _Span()


def test_source_constructed_exit_retains_suppressed_and_unsuppressed_faces():
    """``__exit__`` returned a boolean whose value is symbolic (its truth is
    decided: a ``bool``'s runs no code): the suppressing face under it and
    the restored exception under its negation."""
    original = RaiseEffect.for_builtin("ValueError", blame="boom", occurrence="boom")
    incoming = ExitSet.halted(original, state=_BEFORE_EXIT)
    result = PredicateValue(atomic("fixture:exit-result", []), "renamed-fixture")

    routed = incoming.and_exit_truthiness(
        ExitSet.completed(result), site="renamed-fixture"
    )

    truth = predicate_formula(result, "renamed-fixture")
    assert routed.exits == (
        Completed(truth, _BEFORE_EXIT),
        Halted(not_(truth), original, _BEFORE_EXIT),
    )


def test_an_undecided_exit_result_keeps_its_truth_halt():
    """#7757 NEW-5: ``__exit__`` returned a value whose type is not decided,
    so Python's ``bool()`` of it may run ``__bool__`` / ``__len__`` and
    raise.  Its truth goes through the one truth rule: the suppressing face
    under the keyed truth, the restored exception under its negation, and the
    truth's own undetermined halt under the complement of its completes atom
    -- never the halt-less ``py.truthy`` a direct ``.truth`` used to state."""
    original = RaiseEffect.for_builtin("ValueError", blame="boom", occurrence="boom")
    incoming = ExitSet.halted(original, state=_BEFORE_EXIT)
    result = SymbolicValue(ctor("fixture:exit-result", []))

    routed = incoming.and_exit_truthiness(ExitSet.completed(result), site=_ExitSite())

    completed = [face for face in routed.exits if isinstance(face, Completed)]
    halted = [face for face in routed.exits if isinstance(face, Halted)]
    (done,) = completed
    assert done.value == _BEFORE_EXIT
    assert "python:truth_result" in repr(done.guard)
    assert "py.truthy" not in repr(done.guard)
    restored = [face for face in halted if face.effect is original]
    truth_halts = [
        face for face in halted if isinstance(face.effect, UndeterminedRaiseEffect)
    ]
    assert len(restored) == 1 and len(truth_halts) == 1, routed.exits
    assert truth_halts[0].effect.producer_node_owner == "ExitSet.and_exit_truthiness"
    assert truth_halts[0].owed and done.owed


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
