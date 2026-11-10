"""A cited suppress-set exit splits an undetermined raise on its own type tests.

``ExitSuppressionContract`` and ``Suppresses`` are cited exit dispositions:
``__exit__(type(e), e, tb)`` suppresses exactly when ``issubclass(type(e), T)``
for a suppressed ``T``. A may-raise operation's halt carries the one exception
object it threw (``UndeterminedExceptionValue``) and no type coordinate, and
both arms refused it in ``_require_exception_type_coordinate`` -- a refusal
where the question is real and statable. Now the arm asks the one matcher,
which retains ``adt.is_python_type(e, T)`` (the atom ``except T`` and a
source-constructed exit retain, #7590/#7591): the exit suppresses under it and
the original halt stands under its complement. ``BaseException`` is decided;
an empty set restores; a raise with no subject term stays loud.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.context_manager_contract import Suppresses
from sugar_lift_py_tests.effect.authenticated_raise_locus import AuthenticatedRaiseLocus
from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.effect_router import EffectMatcher
from sugar_lift_py_tests.floor.call_site_value import ExitSuppressionContract
from sugar_lift_py_tests.floor.ground_exit import _builtin_exception_identity
from sugar_lift_py_tests.floor.undetermined_exception_value import (
    UndeterminedExceptionValue,
)
from sugar_lift_py_tests.ir import atomic, or_
from sugar_lift_py_tests.outcome.exit_disposition import (
    RetainedObligation,
    exit_disposition_effect,
)
from sugar_lift_py_tests.outcome.exit_set import Completed, ExitSet, Halted
from sugar_source_tree.panic import SugarNotWritten

_SITE = "suppress_undetermined.py:3:8"


def _undetermined(occurrence=_SITE):
    return UndeterminedRaiseEffect(
        blame=occurrence,
        occurrence=AuthenticatedRaiseLocus.of(occurrence) if occurrence else None,
    )


def _is_type(effect, name):
    identity, _ = _builtin_exception_identity(name)
    subject = UndeterminedExceptionValue(effect.occurrence_id, None)
    return atomic(
        "adt.is_python_type", [subject.to_term(owner="test"), identity]
    )


def _halted(effect):
    return Halted(atomic("true", []), effect, "state")


@pytest.mark.parametrize(
    "disposition",
    (
        ExitSuppressionContract.suppresses(("ValueError",)),
        Suppresses(EffectMatcher(kind="raise", name="ValueError")),
    ),
    ids=("exit-suppression-contract", "suppresses"),
)
def test_undetermined_raise_splits_on_the_suppressed_type(disposition):
    effect = _undetermined()
    verdict = exit_disposition_effect(disposition, _halted(effect))
    assert verdict == RetainedObligation(
        obligation=_is_type(effect, "ValueError"), held=None, failed=effect
    )


def test_several_suppressed_types_retain_one_disjunction():
    effect = _undetermined()
    verdict = exit_disposition_effect(
        ExitSuppressionContract.suppresses(("KeyError", "ValueError")),
        _halted(effect),
    )
    assert isinstance(verdict, RetainedObligation)
    assert verdict.held is None and verdict.failed is effect
    expected = {repr(_is_type(effect, n)) for n in ("KeyError", "ValueError")}
    assert verdict.obligation.kind == "or"
    assert {repr(op) for op in verdict.obligation.operands} == expected


def test_base_exception_is_decided_and_an_empty_set_restores():
    effect = _undetermined()
    assert (
        exit_disposition_effect(
            ExitSuppressionContract.suppresses(("BaseException",)), _halted(effect)
        )
        is None
    )
    assert (
        exit_disposition_effect(ExitSuppressionContract.never_suppresses(), _halted(effect))
        is effect
    )


def test_the_exit_leaves_both_faces_under_complementary_guards():
    effect = _undetermined()
    body = ExitSet((_halted(effect),))
    exit_es = ExitSet.completed(None)
    out = body.and_exit(
        exit_es, disposition=ExitSuppressionContract.suppresses(("ValueError",))
    )
    test = repr(_is_type(effect, "ValueError"))
    completed = [f for f in out.exits if isinstance(f, Completed)]
    halted = [f for f in out.exits if isinstance(f, Halted)]
    assert len(completed) == 1 and len(halted) == 1
    assert halted[0].effect is effect
    assert test in repr(completed[0].guard) and test in repr(halted[0].guard)
    assert repr(completed[0].guard) != repr(halted[0].guard)


def test_a_raise_with_no_subject_term_stays_loud():
    with pytest.raises(SugarNotWritten):
        exit_disposition_effect(
            ExitSuppressionContract.suppresses(("ValueError",)),
            # ``raise thing`` whose operand renders no term: no subject exists.
            _halted(UndeterminedRaiseEffect(blame=_SITE, raised_value=object())),
        )
