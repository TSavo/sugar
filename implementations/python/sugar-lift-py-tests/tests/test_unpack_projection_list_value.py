"""``a, b = <rhs>`` where the reduced RHS is a constructed ``ListValue``.

``ListValue`` had no ``project_sequence_with`` arm, so it fell to the
``FloorValue`` default and panicked with ``requested='project_sequence_with'``.
The reachable path is narrow and worth naming exactly, because the obvious
statement of the gap is wrong: a bare ``a, b = [1, 2]`` submits NO projection
demand -- the unpack sugar reads the display's members directly and the port is
never entered -- so constructed lists are not broadly broken. The one path that
reaches the port is a list UNDER A GUARD, where ``GuardedValue`` distributes the
operation into each face and the list face is asked the question directly.

The guarded-TUPLE twin below is the control: same shape, same distribution, one
face-type answered and its twin panicked. That asymmetry is the finding.

Law: a constructed list answers from its own authenticated members, on the
``project_array`` arm -- the same arm ``ArrayLiteral`` takes. Both project to
``ctor("array", ...)`` in ``to_term``, and the arm choice is observable: it is
what names the value in a decidable arity-mismatch diagnostic. Delegating to
``project_tuple`` would stop the panic while printing a tuple diagnostic for a
list, which is a correct refusal wearing the wrong name.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.floor.guarded_value import GuardedValue
from sugar_lift_py_tests.floor.list_value import ListValue
from sugar_lift_py_tests.floor.scope_rebind import ScopeRebinds
from sugar_lift_py_tests.floor.term_value import TermValue
from sugar_lift_py_tests.floor.tuple_literal_value import TupleLiteralValue
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.ir import atomic, make_var
from sugar_lift_py_tests.operations import SequenceProjectionOperation
from sugar_lift_py_tests.outcome import Complete

GUARD = atomic("py.truthy", [make_var("c")])


def _operation(*names: str) -> SequenceProjectionOperation:
    return SequenceProjectionOperation(
        target_names=names, owner="list-unpack", blame="list-unpack-site"
    )


def _guarded(true_face):
    """``true_face`` under the guard, against a fixed authenticated tuple."""
    return GuardedValue(
        GUARD, true_face, TupleLiteralValue((TermValue(3), TermValue(4)))
    )


# ---------------------------------------------------------------------------
# The reachable path: a list face under a guard, and its tuple twin.
# ---------------------------------------------------------------------------


def test_guarded_list_face_binds_its_authenticated_members() -> None:
    outcome = _operation("a", "b").submit(
        _guarded(ListValue((TermValue(1), TermValue(2)))), None
    )
    assert isinstance(outcome, Complete), outcome
    assert outcome.value == ScopeRebinds(
        (
            ("a", GuardedValue(GUARD, TermValue(1), TermValue(3))),
            ("b", GuardedValue(GUARD, TermValue(2), TermValue(4))),
        )
    )


def test_guarded_tuple_twin_answers_identically() -> None:
    """The control: the same shape with a tuple face, which already worked.

    Both rows must produce the SAME rebinds. If they ever diverge, the list arm
    is doing something other than what its sibling does.
    """
    names = _operation("a", "b")
    from_list = names.submit(_guarded(ListValue((TermValue(1), TermValue(2)))), None)
    from_tuple = names.submit(
        _guarded(TupleLiteralValue((TermValue(1), TermValue(2)))), None
    )
    assert from_list.value == from_tuple.value


def test_unguarded_list_rhs_never_reaches_the_port() -> None:
    """Scoping the finding: this is why the gap is guard-only.

    ``ListValue`` answers the port now, so the bug is not observable here --
    but the reason a bare ``a, b = [1, 2]`` was never broken is that the sugar
    reads the display directly. Asserting the direct submit still keeps this
    row honest about which member testimony is used.
    """
    outcome = _operation("a", "b").submit(
        ListValue((TermValue(7), TermValue(8))), None
    )
    assert isinstance(outcome, Complete), outcome
    assert outcome.value == ScopeRebinds((("a", TermValue(7)), ("b", TermValue(8))))


# ---------------------------------------------------------------------------
# The arm is observable: a decidable mismatch names the list, not a tuple.
# ---------------------------------------------------------------------------


def test_list_arity_mismatch_is_loud_and_names_the_array_arm() -> None:
    with pytest.raises(ConstructionPanic) as raised:
        _operation("a", "b").submit(_guarded(ListValue((TermValue(1),))), None)
    info = raised.value.info
    assert "not enough" in info.observed
    assert "ListValue of 1 members" in info.observed
    assert "ValueError" in info.requested
    # Discrimination: the fix is `project_array`, not `project_tuple`. A tuple
    # diagnostic for a list mismatch is the wrong-name refusal this excludes.
    assert "array unpack arity mismatch" in info.requested
    assert "tuple" not in info.requested


def test_list_members_are_never_fabricated_or_padded() -> None:
    """Too many members is equally loud -- no truncation to fit the targets."""
    with pytest.raises(ConstructionPanic) as raised:
        _operation("a", "b").submit(
            _guarded(ListValue((TermValue(1), TermValue(2), TermValue(3)))), None
        )
    assert "too many" in raised.value.info.observed
