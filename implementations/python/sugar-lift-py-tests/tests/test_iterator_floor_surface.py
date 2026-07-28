"""Synchronous Floor iterator surface: ``iter_with`` / ``next_with``.

Law: iterable authority lives on the Floor value. Callers submit
``IteratorOperation`` / ``NextOperation`` (or the named projectors) and are
exhaustive over outputs — never over container species.

Pins:

* constructed list/tuple answer once with authenticated iterators
* ``__next__`` yields ``NextResult(value, advanced)`` or named StopIteration
* missing authority is the construction-gap default (loud)
* ObjectValue routes through real ``__iter__`` / ``__next__`` coordinates
* no second dispatch table / admission ladder
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.caller_parameter_contract import project_iter, project_next
from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
from sugar_lift_py_tests.floor.iterator_value import (
    ListIteratorValue,
    NextResult,
    TupleIteratorValue,
)
from sugar_lift_py_tests.floor.list_value import ListValue
from sugar_lift_py_tests.floor.none_value import NoneValue
from sugar_lift_py_tests.floor.object_value import ObjectValue
from sugar_lift_py_tests.floor.term_value import TermValue
from sugar_lift_py_tests.floor.tuple_value import TupleValue
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.operations import IteratorOperation, NextOperation
from sugar_lift_py_tests.outcome import Complete, Incomplete

SITE = "iterator-surface-site"


def _iter_op(*, owner: str = "test_iter") -> IteratorOperation:
    return IteratorOperation(owner=owner, blame=SITE)


def _next_op(*, owner: str = "test_next") -> NextOperation:
    return NextOperation(owner=owner, blame=SITE)


# ---------------------------------------------------------------------------
# Exact iterable → authenticated iterator
# ---------------------------------------------------------------------------


def test_list_iter_with_yields_list_iterator() -> None:
    members = (TermValue(1), TermValue(2), TermValue(3))
    outcome = _iter_op().submit(ListValue(members), None)
    assert isinstance(outcome, Complete), outcome
    assert outcome.value == ListIteratorValue(members, index=0)


def test_tuple_iter_with_yields_tuple_iterator() -> None:
    members = (TermValue(10), TermValue(20))
    outcome = _iter_op().submit(TupleValue(members), None)
    assert isinstance(outcome, Complete), outcome
    assert outcome.value == TupleIteratorValue(members, index=0)


def test_project_iter_is_the_production_edge_for_list() -> None:
    members = (TermValue(7),)
    outcome = project_iter(ListValue(members), SITE)
    assert isinstance(outcome, Complete)
    assert outcome.value == ListIteratorValue(members, index=0)


# ---------------------------------------------------------------------------
# Exact iterator → NextResult or named StopIteration
# ---------------------------------------------------------------------------


def test_list_next_yields_value_and_advanced_iterator() -> None:
    members = (TermValue(1), TermValue(2))
    it = ListIteratorValue(members, index=0)
    outcome = _next_op().submit(it, None)
    assert isinstance(outcome, Complete), outcome
    assert isinstance(outcome.value, NextResult)
    assert outcome.value.value == TermValue(1)
    assert outcome.value.advanced == ListIteratorValue(members, index=1)


def test_list_next_exhausts_with_named_stop_iteration() -> None:
    it = ListIteratorValue((TermValue(1),), index=1)
    outcome = _next_op().submit(it, None)
    assert isinstance(outcome, Incomplete), outcome
    assert isinstance(outcome.effect, RaiseEffect)
    assert outcome.effect.exception_name == "StopIteration"


def test_tuple_next_walks_then_stops() -> None:
    members = (TermValue(9),)
    it = TupleIteratorValue(members, index=0)
    first = _next_op().submit(it, None)
    assert isinstance(first, Complete)
    assert first.value.value == TermValue(9)
    second = _next_op().submit(first.value.advanced, None)
    assert isinstance(second, Incomplete)
    assert second.effect.exception_name == "StopIteration"


def test_project_next_matches_operation_submit() -> None:
    members = (TermValue(4), TermValue(5))
    it = ListIteratorValue(members, index=0)
    via_op = _next_op(owner="project_next").submit(it, None)
    via_proj = project_next(it, SITE)
    assert via_op == via_proj
    assert via_proj.value.value == TermValue(4)
    assert via_proj.value.advanced == ListIteratorValue(members, index=1)


def test_empty_list_iterator_stops_immediately() -> None:
    outcome = _next_op().submit(ListIteratorValue((), index=0), None)
    assert isinstance(outcome, Incomplete)
    assert outcome.effect.exception_name == "StopIteration"


def test_stop_iteration_is_not_type_error() -> None:
    """Exhaustion must not wear TypeError or a silent Incomplete without identity."""
    outcome = _next_op().submit(ListIteratorValue((), index=0), None)
    assert isinstance(outcome, Incomplete)
    assert outcome.effect.exception_name != "TypeError"
    assert outcome.effect.exception_name == "StopIteration"


# ---------------------------------------------------------------------------
# Missing authority is loud (construction gap)
# ---------------------------------------------------------------------------


def test_none_has_no_iter_authority() -> None:
    with pytest.raises(ConstructionPanic) as caught:
        _iter_op().submit(NoneValue(), None)
    assert "iter_with" in str(caught.value)
    assert "NoneValue" in str(caught.value)


def test_term_has_no_iter_authority() -> None:
    with pytest.raises(ConstructionPanic) as caught:
        _iter_op().submit(TermValue(1), None)
    assert "iter_with" in str(caught.value)


def test_list_has_no_next_authority() -> None:
    """A list is iterable, not an iterator — ``next(list)`` is a gap here."""
    with pytest.raises(ConstructionPanic) as caught:
        _next_op().submit(ListValue((TermValue(1),)), None)
    assert "next_with" in str(caught.value)


def test_object_without_iter_method_is_loud() -> None:
    """ObjectValue without constructor-bound ``__iter__`` cannot invent one."""
    bare = ObjectValue("Bare", ())
    with pytest.raises(ConstructionPanic) as caught:
        _iter_op(owner="project_iter").submit(bare, None)
    text = str(caught.value)
    assert "__iter__" in text or "Bare.__iter__" in text


def test_object_without_next_method_is_loud() -> None:
    bare = ObjectValue("Bare", ())
    with pytest.raises(ConstructionPanic) as caught:
        _next_op(owner="project_next").submit(bare, None)
    text = str(caught.value)
    assert "__next__" in text or "Bare.__next__" in text


# ---------------------------------------------------------------------------
# Immutability / no silent reuse
# ---------------------------------------------------------------------------


def test_next_does_not_mutate_prior_iterator() -> None:
    members = (TermValue(1), TermValue(2))
    original = ListIteratorValue(members, index=0)
    outcome = _next_op().submit(original, None)
    assert original.index == 0
    assert outcome.value.advanced.index == 1
    assert original is not outcome.value.advanced


def test_full_list_walk_via_projectors() -> None:
    members = (TermValue(1), TermValue(2), TermValue(3))
    it_out = project_iter(ListValue(members), SITE)
    assert isinstance(it_out, Complete)
    cursor = it_out.value
    seen: list[object] = []
    for _ in range(3):
        step = project_next(cursor, SITE)
        assert isinstance(step, Complete)
        seen.append(step.value.value)
        cursor = step.value.advanced
    stop = project_next(cursor, SITE)
    assert isinstance(stop, Incomplete)
    assert stop.effect.exception_name == "StopIteration"
    assert seen == [TermValue(1), TermValue(2), TermValue(3)]
