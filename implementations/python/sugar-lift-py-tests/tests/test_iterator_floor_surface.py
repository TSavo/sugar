"""Synchronous Floor iterator surface: ``iter_with`` / ``next_with``.

Law: iterable authority lives on the Floor value. Callers submit
``IteratorOperation`` / ``NextOperation`` (or the named projectors) and are
exhaustive over outputs — never over container species.

Pins:

* constructed list/tuple answer once with authenticated iterators
* ``__next__`` yields ``NextResult(value, advanced)`` or named StopIteration
* exhaustion cites authenticated operation occurrence + builtin type coordinate
* missing authority is the construction-gap default (loud)
* ObjectValue routes through real ``__iter__`` / ``__next__`` coordinates
* no second dispatch table / admission ladder
* synthetic string sites cannot mint StopIteration identity from spelling
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import pytest

from sugar_lift_py_tests.caller_parameter_contract import project_iter, project_next
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
from sugar_lift_py_tests.floor.floor_value import FloorValue
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
from sugar_lift_py_tests.ir import ctor, str_const
from sugar_lift_py_tests.operations import IteratorOperation, NextOperation
from sugar_lift_py_tests.outcome import Complete, Incomplete
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import FunctionDef
from sugar_source_tree.tree import SourceFile


def _tree(source: str, name: str = "iterator_surface.py") -> SourceFile:
    return SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _site(source: str = "def f(xs):\n    return next(iter(xs))\n"):
    """Authenticated SourceFile fragment — workspace-relative ground-exit locus."""
    tree = _tree(source)
    function = next(n for n in tree.nodes() if isinstance(n, FunctionDef))
    # Body statement fragment carries filename + unit for ground_raise_effect.
    return function.body[0].fragment


def _stopiteration_type_identity():
    return ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const("StopIteration")],
    )


def _iter_op(*, owner: str = "test_iter", site=None) -> IteratorOperation:
    return IteratorOperation(owner=owner, blame=site if site is not None else _site())


def _next_op(*, owner: str = "test_next", site=None) -> NextOperation:
    return NextOperation(owner=owner, blame=site if site is not None else _site())


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
    site = _site()
    members = (TermValue(7),)
    outcome = project_iter(ListValue(members), site)
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
    site = _site()
    it = ListIteratorValue((TermValue(1),), index=1)
    outcome = _next_op(owner="project_next", site=site).submit(it, None)
    assert isinstance(outcome, Incomplete), outcome
    assert isinstance(outcome.effect, RaiseEffect)
    assert outcome.effect.exception_name == "StopIteration"
    # Exact builtin type coordinate — not spelling-only identity.
    assert outcome.effect.exception_type_coordinate == _stopiteration_type_identity()
    # Exact next-operation occurrence + owner from the authenticated fragment.
    assert outcome.effect.producer_node_owner == "project_next"
    assert outcome.effect.occurrence_id == str(site)
    assert outcome.effect.occurrence_id == str(site)


def test_tuple_next_walks_then_stops() -> None:
    site = _site()
    members = (TermValue(9),)
    it = TupleIteratorValue(members, index=0)
    first = _next_op(site=site).submit(it, None)
    assert isinstance(first, Complete)
    assert first.value.value == TermValue(9)
    second = _next_op(owner="project_next", site=site).submit(
        first.value.advanced, None
    )
    assert isinstance(second, Incomplete)
    assert second.effect.exception_name == "StopIteration"
    assert second.effect.exception_type_coordinate == _stopiteration_type_identity()
    assert second.effect.occurrence_id == str(site)


def test_project_next_matches_operation_submit() -> None:
    site = _site()
    members = (TermValue(4), TermValue(5))
    it = ListIteratorValue(members, index=0)
    via_op = _next_op(owner="project_next", site=site).submit(it, None)
    via_proj = project_next(it, site)
    assert via_op == via_proj
    assert via_proj.value.value == TermValue(4)
    assert via_proj.value.advanced == ListIteratorValue(members, index=1)


def test_empty_list_iterator_stops_immediately() -> None:
    site = _site()
    outcome = _next_op(owner="project_next", site=site).submit(
        ListIteratorValue((), index=0), None
    )
    assert isinstance(outcome, Incomplete)
    assert outcome.effect.exception_name == "StopIteration"
    assert outcome.effect.exception_type_coordinate == _stopiteration_type_identity()
    assert outcome.effect.occurrence_id == str(site)
    assert outcome.effect.producer_node_owner == "project_next"


def test_stop_iteration_is_not_type_error() -> None:
    """Exhaustion must not wear TypeError or a silent Incomplete without identity."""
    site = _site()
    outcome = _next_op(site=site).submit(ListIteratorValue((), index=0), None)
    assert isinstance(outcome, Incomplete)
    assert outcome.effect.exception_name != "TypeError"
    assert outcome.effect.exception_name == "StopIteration"
    assert outcome.effect.exception_type_coordinate == _stopiteration_type_identity()


# ---------------------------------------------------------------------------
# Synthetic / missing authority cannot mint StopIteration
# ---------------------------------------------------------------------------


def test_string_site_cannot_mint_stop_iteration() -> None:
    """Missing-authority twin: prose blame cannot fabricate exception identity."""
    with pytest.raises(ConstructionPanic) as caught:
        project_next(ListIteratorValue((), index=0), "iterator-surface-site")
    text = str(caught.value)
    assert "fragment" in text.lower() or "locus" in text.lower() or "source" in text.lower()
    assert "StopIteration" not in text or "no source fragment" in text
    # Lying twin: claiming string blame yields a greened Incomplete StopIteration.
    with pytest.raises(ConstructionPanic):
        out = project_next(ListIteratorValue((), index=0), "iterator-surface-site")
        assert isinstance(out, Incomplete)
        assert out.effect.exception_name == "StopIteration"


def test_same_name_foreign_coordinate_is_not_truthful_stop() -> None:
    """Spelling 'StopIteration' under a foreign coordinate is not the exit."""
    site = _site()
    truthful = project_next(ListIteratorValue((), index=0), site)
    assert isinstance(truthful, Incomplete)
    effect = truthful.effect
    assert effect.exception_name == "StopIteration"
    assert effect.exception_type_coordinate == _stopiteration_type_identity()
    foreign_type = ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const("ValueError")],
    )
    foreign = replace(
        effect,
        exception_type_coordinate=foreign_type,
        exception_type_mro=(foreign_type,),
        occurrence="pytest.raises:foreign-boundary",
        producer_node_owner="pytest.raises",
    )
    assert foreign.exception_name == effect.exception_name  # spelling alone
    assert foreign.exception_type_coordinate != effect.exception_type_coordinate
    assert foreign.occurrence != effect.occurrence
    assert foreign != effect
    with pytest.raises(AssertionError):
        assert foreign == effect
    with pytest.raises(AssertionError):
        assert foreign.exception_type_coordinate == _stopiteration_type_identity()


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
    site = _site()
    members = (TermValue(1), TermValue(2), TermValue(3))
    it_out = project_iter(ListValue(members), site)
    assert isinstance(it_out, Complete)
    cursor = it_out.value
    seen: list[object] = []
    for _ in range(3):
        step = project_next(cursor, site)
        assert isinstance(step, Complete)
        seen.append(step.value.value)
        cursor = step.value.advanced
    stop = project_next(cursor, site)
    assert isinstance(stop, Incomplete)
    assert stop.effect.exception_name == "StopIteration"
    assert stop.effect.exception_type_coordinate == _stopiteration_type_identity()
    assert stop.effect.producer_node_owner == "project_next"
    assert stop.effect.occurrence_id == str(site)
    assert seen == [TermValue(1), TermValue(2), TermValue(3)]


# ---------------------------------------------------------------------------
# Discrimination twins: renamed / wrong-definition / wrong-occurrence / cross-wired
# ---------------------------------------------------------------------------


def test_renamed_method_is_not_the_iterator_surface() -> None:
    """A Floor that only answers a renamed method is not ``iter_with``."""

    @dataclass(frozen=True)
    class _RenamedOnly(TermValue):
        def iterate_with(self, operation, ctx):  # renamed — not the surface
            del operation, ctx
            return Complete(ListIteratorValue((), index=0))

    receiver = _RenamedOnly(0)
    assert hasattr(receiver, "iterate_with")
    assert receiver.iter_with is FloorValue.iter_with or callable(
        getattr(receiver, "iter_with", None)
    )
    with pytest.raises(ConstructionPanic) as caught:
        _iter_op().submit(receiver, None)
    assert "iter_with" in str(caught.value)
    with pytest.raises(ConstructionPanic):
        IteratorOperation(owner="renamed", blame=_site()).submit(receiver, None)


def test_wrong_definition_stop_is_not_type_error() -> None:
    """Exhaustion must not be redefinable as TypeError or empty Complete."""
    site = _site()
    outcome = project_next(ListIteratorValue((), index=0), site)
    assert isinstance(outcome, Incomplete)
    assert outcome.effect.exception_name == "StopIteration"
    with pytest.raises(AssertionError):
        assert outcome.effect.exception_name == "TypeError"
    with pytest.raises(AssertionError):
        assert isinstance(outcome, Complete)


def test_wrong_occurrence_stop_is_not_truthful() -> None:
    """Same exception name under a foreign occurrence is not the operation exit."""
    site = _site()
    truthful = project_next(ListIteratorValue((), index=0), site)
    assert isinstance(truthful, Incomplete)
    effect = truthful.effect
    assert effect.exception_name == "StopIteration"
    foreign = replace(
        effect,
        occurrence="pytest.raises:foreign-boundary",
        producer_node_owner="pytest.raises",
    )
    assert foreign.exception_name == effect.exception_name == "StopIteration"
    assert foreign.occurrence != effect.occurrence
    assert foreign.producer_node_owner != effect.producer_node_owner
    assert foreign != effect
    with pytest.raises(AssertionError):
        assert foreign == effect
    with pytest.raises(AssertionError):
        assert foreign.producer_node_owner == "project_next"


def test_cross_wired_list_iterator_is_not_tuple_iterator() -> None:
    """List and tuple iterators are distinct authenticated Floors."""
    site = _site()
    members = (TermValue(1), TermValue(2))
    list_it = project_iter(ListValue(members), site).value
    tuple_it = project_iter(TupleValue(members), site).value
    assert isinstance(list_it, ListIteratorValue)
    assert isinstance(tuple_it, TupleIteratorValue)
    assert list_it != tuple_it
    with pytest.raises(AssertionError):
        assert list_it == tuple_it
    step = project_next(list_it, site)
    assert isinstance(step.value.advanced, ListIteratorValue)
    assert not isinstance(step.value.advanced, TupleIteratorValue)


def test_cross_wired_iter_and_next_methods_are_distinct() -> None:
    """``iter_with`` and ``next_with`` are different doors — not interchangeable."""
    site = _site()
    assert IteratorOperation.method_name == "iter_with"
    assert NextOperation.method_name == "next_with"
    assert IteratorOperation.method_name != NextOperation.method_name
    assert isinstance(project_iter(ListValue((TermValue(1),)), site), Complete)
    with pytest.raises(ConstructionPanic):
        project_next(ListValue((TermValue(1),)), site)
    stop = project_next(ListIteratorValue((), index=0), site)
    assert isinstance(stop, Incomplete)
    with pytest.raises(ConstructionPanic):
        project_iter(ListIteratorValue((), index=0), site)


# ---------------------------------------------------------------------------
# Production projector equality stays exact (no silent iter/next enrollment)
# ---------------------------------------------------------------------------


def test_production_native_operator_projector_equality_stays_exact() -> None:
    """Named project_iter/project_next must not break the closed enrollment tooth."""
    from sugar_lift_py_tests.caller_parameter_contract import (
        _NATIVE_OPERATION_PROJECTORS,
        production_native_operation_operators,
    )

    production = production_native_operation_operators()
    projectors = frozenset(_NATIVE_OPERATION_PROJECTORS)
    assert production == projectors
    assert "iter" not in projectors
    assert "next" not in projectors
    assert callable(project_iter)
    assert callable(project_next)
    assert "project_iter" not in projectors
    assert "project_next" not in projectors
    with pytest.raises(AssertionError):
        assert "iter" in production
