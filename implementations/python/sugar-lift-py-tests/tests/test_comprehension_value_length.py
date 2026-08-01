"""Test-first law for list-comprehension length testimony."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.floor import CallSiteValue, ComprehensionValue, TermValue
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.ir import atomic, ctor
from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet, Halted


@dataclass(frozen=True)
class _Pending:
    candidate_cid: str
    demands: tuple = ()


@dataclass(frozen=True)
class _ListcompLookalike:
    name: str = "py.listcomp"


@pytest.mark.parametrize(
    ("elements", "expected"),
    [
        ((), 0),
        ((TermValue(7), TermValue(9)), 2),
        ((TermValue(7), TermValue(7), TermValue(9)), 3),
    ],
)
def test_listcomp_finite_roster_length_counts_exact_members(
    elements, expected
) -> None:
    value = ComprehensionValue(
        ctor("py.listcomp", ()), finite_elements=elements
    )

    outcome = value.length(object())

    assert type(outcome) is Complete
    assert outcome.value == TermValue(expected)


def test_listcomp_without_finite_roster_is_exact_bodyless_builtin_call() -> None:
    term = ctor("py.listcomp", (ctor("source", ()),))
    value = ComprehensionValue(term, finite_elements=None)
    site = object()

    outcome = value.length(site)

    assert type(outcome) is Complete
    result = outcome.value
    assert type(result) is CallSiteValue
    assert result.target_name == "len"
    assert len(result.arg_values) == 1
    assert result.arg_values[0] is value
    assert result.parameters == ()
    assert result.term == ctor("call:len", (term,), symbol_kind="builtin")
    assert result.body is None
    assert result.site is site


@pytest.mark.parametrize(
    "term",
    [
        ctor("py.setcomp", ()),
        ctor("py.dictcomp", ()),
        ctor("py.generatorexp", ()),
        ctor("foreign.comprehension", ()),
        _ListcompLookalike(),
    ],
)
def test_non_listcomp_constructor_keeps_existing_loud_length_floor(term) -> None:
    value = ComprehensionValue(
        term,
        finite_elements=(TermValue(1), TermValue(1)),
    )

    with pytest.raises(ConstructionPanic):
        value.length(object())


def test_valid_foreign_listcomp_constructor_and_site_are_retained_exactly() -> None:
    first_term = ctor("py.listcomp", (ctor("source:first", ()),))
    foreign_term = ctor("py.listcomp", (ctor("source:foreign", ()),))
    first_value = ComprehensionValue(first_term, finite_elements=None)
    foreign_value = ComprehensionValue(foreign_term, finite_elements=None)
    first_site = object()
    foreign_site = object()

    first = first_value.length(first_site).value
    foreign = foreign_value.length(foreign_site).value

    assert type(first) is CallSiteValue
    assert type(foreign) is CallSiteValue
    assert first.arg_values[0] is first_value
    assert foreign.arg_values[0] is foreign_value
    assert first.site is first_site
    assert foreign.site is foreign_site
    assert first.term == ctor("call:len", (first_term,), symbol_kind="builtin")
    assert foreign.term == ctor(
        "call:len", (foreign_term,), symbol_kind="builtin"
    )
    assert foreign.term != first.term


def test_exitset_listcomp_length_preserves_halt_guard_and_pending() -> None:
    halted_pending = _Pending("pending:halted")
    completed_pending = _Pending("pending:completed")
    halted = Halted(
        atomic("test:halted", ()),
        RaiseEffect.for_builtin("ValueError", occurrence="source.py:1:0"),
        TermValue(41),
        pending_contracts=(halted_pending,),
    )
    completed = Completed(
        atomic("test:completed", ()),
        ComprehensionValue(
            ctor("py.listcomp", ()), finite_elements=(TermValue(1), TermValue(2))
        ),
        pending_contracts=(completed_pending,),
    )

    result = ExitSet((halted, completed)).and_then(
        lambda value: value.length(object())
    )

    halted_after = next(face for face in result.exits if isinstance(face, Halted))
    completed_after = next(
        face for face in result.exits if isinstance(face, Completed)
    )
    assert halted_after is halted
    assert halted_after.guard == halted.guard
    assert halted_after.pending_contracts == (halted_pending,)
    assert completed_after.value == TermValue(2)
    assert completed_after.guard == completed.guard
    assert completed_after.pending_contracts == (completed_pending,)
