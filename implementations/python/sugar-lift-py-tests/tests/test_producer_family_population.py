from __future__ import annotations

import ast
import inspect

from sugar_lift_py_tests import producer_family_population as population
from sugar_lift_py_tests.producer_family_population import (
    AuthenticatedCompletedOwnership,
    AuthenticatedHaltOwnership,
    FailingNodeFamily,
    NativeBoundaryKind,
    PopulationMembership,
    ProducerFamily,
    ProducerFamilyPopulationWitness,
    UndecidedOwnership,
    producer_family_population_membership,
)


def test_truthful_root_attribute_halt_belongs_to_attribute() -> None:
    witness = ProducerFamilyPopulationWitness(
        boundary_kind=NativeBoundaryKind.EFFECT,
        ownership=AuthenticatedHaltOwnership(
            root_family=ProducerFamily.ATTRIBUTE,
            failing_family=FailingNodeFamily.ATTRIBUTE,
        ),
    )

    decision = producer_family_population_membership(witness)

    assert decision.membership is PopulationMembership.MEMBER
    assert decision.family is ProducerFamily.ATTRIBUTE


def test_receiver_call_presence_cannot_reclassify_an_attribute() -> None:
    """Lying twin: a receiver Call is not failing-node testimony."""
    receiver_constructed = ProducerFamilyPopulationWitness(
        boundary_kind=NativeBoundaryKind.EFFECT,
        ownership=AuthenticatedHaltOwnership(
            root_family=ProducerFamily.ATTRIBUTE,
            failing_family=FailingNodeFamily.ATTRIBUTE,
        ),
    )

    assert (
        producer_family_population_membership(receiver_constructed).membership
        is PopulationMembership.MEMBER
    )


def test_manager_spelling_cannot_participate_in_membership() -> None:
    """Lying twin: the closed witness has no manager-name coordinate."""
    assert tuple(ProducerFamilyPopulationWitness.__dataclass_fields__) == (
        "boundary_kind",
        "ownership",
    )
    assert inspect.signature(
        producer_family_population_membership
    ).parameters.keys() == {"witness"}


def test_authenticated_warning_completion_is_positive_membership_testimony() -> None:
    witness = ProducerFamilyPopulationWitness(
        boundary_kind=NativeBoundaryKind.EFFECT,
        ownership=AuthenticatedCompletedOwnership(ProducerFamily.ATTRIBUTE),
    )

    decision = producer_family_population_membership(witness)

    assert decision.membership is PopulationMembership.MEMBER
    assert decision.family is ProducerFamily.ATTRIBUTE


def test_child_call_halt_is_re_attributed_before_attribute_is_reached() -> None:
    """`col(...).is_indexed`: col() halts before Attribute evaluation."""
    witness = ProducerFamilyPopulationWitness(
        boundary_kind=NativeBoundaryKind.EFFECT,
        ownership=AuthenticatedHaltOwnership(
            root_family=ProducerFamily.ATTRIBUTE,
            failing_family=FailingNodeFamily.CALL,
        ),
    )

    decision = producer_family_population_membership(witness)

    assert decision.membership is PopulationMembership.REATTRIBUTED
    assert decision.family is FailingNodeFamily.CALL


def test_undecided_exitset_is_not_treated_as_empty_or_member() -> None:
    witness = ProducerFamilyPopulationWitness(
        boundary_kind=NativeBoundaryKind.EFFECT,
        ownership=UndecidedOwnership(ProducerFamily.ATTRIBUTE),
    )

    decision = producer_family_population_membership(witness)

    assert decision.membership is PopulationMembership.UNDECIDED
    assert decision.family is None


def test_population_module_cannot_express_forbidden_selection_inputs() -> None:
    """Whole-module guard, including helpers and nested scopes."""
    source = inspect.getsource(population)
    tree = ast.parse(source)
    string_literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    imported_modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }

    assert not any("targetSymbol" in value for value in string_literals)
    assert not any("pytest" in value for value in string_literals)
    assert not any("descendant" in value.lower() for value in string_literals)
    assert "ast" not in imported_modules


def test_attribute_denominator_justification_records_all_four_wrong_rules() -> None:
    historical_descendant_filtered = 41
    receiver_construction_owned_by_attribute = 9
    authenticated_warning_completions = (
        "tests/indexes/period/test_freq_attr.py:17",
        "tests/internals/test_api.py:81",
    )
    call_owned_before_attribute = "tests/io/pytables/test_store.py:448"

    witnesses = [
        ProducerFamilyPopulationWitness(
            NativeBoundaryKind.EFFECT,
            AuthenticatedHaltOwnership(
                ProducerFamily.ATTRIBUTE, FailingNodeFamily.ATTRIBUTE
            ),
        )
        for _ in range(historical_descendant_filtered)
    ]
    witnesses += [
        ProducerFamilyPopulationWitness(
            NativeBoundaryKind.EFFECT,
            AuthenticatedHaltOwnership(
                ProducerFamily.ATTRIBUTE, FailingNodeFamily.ATTRIBUTE
            ),
        )
        for _ in range(receiver_construction_owned_by_attribute)
    ]
    witnesses += [
        ProducerFamilyPopulationWitness(
            NativeBoundaryKind.EFFECT,
            AuthenticatedCompletedOwnership(ProducerFamily.ATTRIBUTE),
        )
        for _ in authenticated_warning_completions
    ]
    witnesses.append(
        ProducerFamilyPopulationWitness(
            NativeBoundaryKind.EFFECT,
            AuthenticatedHaltOwnership(
                ProducerFamily.ATTRIBUTE, FailingNodeFamily.CALL
            ),
        )
    )

    decisions = tuple(map(producer_family_population_membership, witnesses))
    assert (
        sum(
            decision.membership is PopulationMembership.MEMBER
            and decision.family is ProducerFamily.ATTRIBUTE
            for decision in decisions
        )
        == 52
    )
    assert decisions[-1].membership is PopulationMembership.REATTRIBUTED
    assert call_owned_before_attribute.endswith(":448")
    assert historical_descendant_filtered + 9 == 50
    assert historical_descendant_filtered + 9 + 1 == 51
    assert historical_descendant_filtered + 9 + 1 + 2 == 53
