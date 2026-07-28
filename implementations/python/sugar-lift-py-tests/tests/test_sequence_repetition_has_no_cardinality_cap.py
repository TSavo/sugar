"""Sequence repetition refuses no cardinality and drops no element.

List and tuple each carried a private ``multiply`` arm that PANICKED once a
concrete repetition exceeded 128 elements, reporting perfectly ordinary
repetitions on the installed pandas tree as construction gaps. One law now
owns both categories: above the eager-materialization budget the repetition is
FOLDED to the same closed ``python:sequence_repeat`` coordinate the opaque-count
arm already emits -- the same value, not an approximation of it.

Each positive arm is paired with a discriminating arm: a shape that must NOT
take the same door. Cardinalities are asserted exactly, because a repetition
law that merely produced "not 1" element would be satisfied by 0 and by 2.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.floor import (
    ListValue,
    SymbolicValue,
    TermValue,
    TupleValue,
)
from sugar_lift_py_tests.floor.sequence_repetition import (
    EAGER_MATERIALIZATION_BUDGET,
    repetition_term,
)
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.ir import _Ctor
from sugar_lift_py_tests.outcome import Complete

SEQUENCES = (ListValue, TupleValue)
SITE = "repetition-site"


# -- positive arm: at or below the budget, the repetition is materialized -----


@pytest.mark.parametrize("sequence_type", SEQUENCES)
def test_repetition_at_the_budget_materializes_every_element(sequence_type) -> None:
    element = TermValue(7)

    outcome = sequence_type((element,)).multiply(
        TermValue(EAGER_MATERIALIZATION_BUDGET), SITE
    )

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, sequence_type)
    # Exact cardinality: 128 elements, every one the repeated element.
    assert len(outcome.value.elements) == EAGER_MATERIALIZATION_BUDGET
    assert outcome.value.elements == (element,) * EAGER_MATERIALIZATION_BUDGET


# -- positive arm: one element past the budget no longer panics ---------------


@pytest.mark.parametrize("sequence_type", SEQUENCES)
def test_one_element_past_the_budget_folds_instead_of_panicking(
    sequence_type,
) -> None:
    sequence = sequence_type((TermValue(7),))
    count = TermValue(EAGER_MATERIALIZATION_BUDGET + 1)

    outcome = sequence.multiply(count, SITE)

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, SymbolicValue)
    assert outcome.value.term == repetition_term(sequence, count, SITE)


@pytest.mark.parametrize("sequence_type", SEQUENCES)
def test_a_cardinality_no_machine_could_materialize_still_constructs(
    sequence_type,
) -> None:
    """The old arm panicked here; nothing about the VALUE is unknown."""
    sequence = sequence_type((TermValue(7),))
    count = TermValue(10**12)

    outcome = sequence.multiply(count, SITE)

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, SymbolicValue)
    term = outcome.value.term
    assert isinstance(term, _Ctor)
    assert term.name == "python:sequence_repeat"
    assert term.args[1] == count.to_term(owner=SITE)


@pytest.mark.parametrize("sequence_type", SEQUENCES)
def test_no_cardinality_makes_repetition_panic(sequence_type) -> None:
    """The discrimination that names the law: NO count is a construction gap."""
    sequence = sequence_type((TermValue(1), TermValue(2)))

    for count in (0, 1, 63, 64, 65, 128, 129, 10**6, 10**15):
        outcome = sequence.multiply(TermValue(count), SITE)
        assert isinstance(outcome, Complete), count


# -- discriminating arm: the folded form is the OPAQUE-count coordinate -------


@pytest.mark.parametrize("sequence_type", SEQUENCES)
def test_folded_concrete_count_is_the_same_construction_as_an_opaque_count(
    sequence_type,
) -> None:
    """One coordinate, not a second parallel spelling for large concretes."""
    sequence = sequence_type((TermValue(7),))
    opaque = SymbolicValue(TermValue(3).to_term(owner=SITE))

    folded = sequence.multiply(TermValue(10**9), SITE).value.term
    opaque_folded = sequence.multiply(opaque, SITE).value.term

    assert isinstance(folded, _Ctor) and isinstance(opaque_folded, _Ctor)
    assert folded.name == opaque_folded.name == "python:sequence_repeat"
    # Same receiver term on both; only the count operand differs.
    assert folded.args[0] == opaque_folded.args[0]
    assert folded.args[1] != opaque_folded.args[1]


# -- discriminating arm: a known-invalid count is still a typed TypeError -----


@pytest.mark.parametrize("sequence_type", SEQUENCES)
def test_a_known_invalid_count_does_not_reach_either_repetition_arm(
    sequence_type, tmp_path
) -> None:
    """Removing the cap must not have widened the door to non-index counts.

    A source-decided non-``__index__`` count is authenticated TypeError
    RaiseValue on a workspace-relative fragment.
    """
    del tmp_path
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_lift_py_tests.floor import RaiseValue
    from sugar_lift_py_tests.outcome import Complete
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_source_tree.tree import SourceFile

    source = "def witness():\n    return [1] * 1.5\n"
    fragment = next(
        SourceFile(
            (source, "sequence_repeat.py", blake3_512_of(source.encode())),
            construction_context=TreeConstructionContextV1.for_source_call_construction(),
        ).functions()
    ).fragment

    outcome = sequence_type((TermValue(1),)).multiply(TermValue(1.5), fragment)

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, RaiseValue)
    assert outcome.value.effect.exception_name == "TypeError"


# -- discriminating arm: each category rebuilds ITSELF ------------------------


def test_each_sequence_category_rebuilds_its_own_shape() -> None:
    """One shared law, but a list never materializes as a tuple."""
    element = TermValue(7)

    from_list = ListValue((element,)).multiply(TermValue(3), SITE).value
    from_tuple = TupleValue((element,)).multiply(TermValue(3), SITE).value

    assert type(from_list) is ListValue
    assert type(from_tuple) is TupleValue
    assert len(from_list.elements) == 3
    assert len(from_tuple.elements) == 3


# -- the value with no elements ----------------------------------------------


@pytest.mark.parametrize("sequence_type", SEQUENCES)
def test_an_empty_sequence_repeats_to_empty_at_any_count(sequence_type) -> None:
    """len 0 * huge n is 0, materializable -- never folded, never a panic."""
    outcome = sequence_type(()).multiply(TermValue(10**12), SITE)

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, sequence_type)
    assert len(outcome.value.elements) == 0


@pytest.mark.parametrize("sequence_type", SEQUENCES)
def test_a_negative_count_repeats_to_empty(sequence_type) -> None:
    outcome = sequence_type((TermValue(7),)).multiply(TermValue(-4), SITE)

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, sequence_type)
    assert len(outcome.value.elements) == 0


# -- the gap that remains: no sequence category invented a repetition ---------


def test_a_value_off_the_sequence_floor_still_panics_and_names_its_pair() -> None:
    """`panic = gap`: closing the cardinality gap closed no OTHER gap."""
    from sugar_lift_py_tests.floor.floor_value import FloorValue

    class OffFloor(FloorValue):
        pass

    with pytest.raises(ConstructionPanic) as raised:
        OffFloor().multiply(TermValue(3), SITE)

    info = raised.value.info
    assert info.owner == "multiply"
    assert info.observed == "OffFloor"
    # The pair, not just the left operand -- the dispatch unit is (owner, pair).
    assert "TermValue" in info.requested
    assert "OffFloor.multiply for TermValue" in info.fix
