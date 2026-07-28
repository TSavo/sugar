"""The source ``If`` producer must supply one condition-owned result slot."""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor.branch_result_coordinate import (
    BranchResultAuthentication,
    branch_result_guard,
)
from sugar_lift_py_tests.outcome import Complete, ExitSet, Halted
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.binding_state import branch_result_slot
from sugar_source_tree.nodes import Call, Compare, If
from sugar_source_tree.panic import BackendDefect
from sugar_source_tree.tree import SourceFile


def _tree(source: str) -> SourceFile:
    return SourceFile(
        (source, "if-construct-slot.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _two_ifs() -> tuple[If, If]:
    branches = tuple(
        node
        for node in _tree(
            "if left is right:\n"
            "    assert left is right\n"
            "else:\n"
            "    assert left is not right\n"
            "if nearby:\n"
            "    pass\n"
        ).nodes()
        if isinstance(node, If)
    )
    assert len(branches) == 2
    return branches


def test_raw_source_if_routes_through_one_condition_owned_slot() -> None:
    branch, _ = _two_ifs()

    sugar = branch.sugar()
    outcome = sugar.desugar(None)

    slot = branch_result_slot(branch.test)
    assert sugar.branch_slot == slot
    assert isinstance(outcome, Complete)
    authentications = tuple(
        entry
        for entry in outcome.value.unconditional_entries
        if isinstance(entry, BranchResultAuthentication)
    )
    assert len(authentications) == 1
    assert authentications[0].slot == slot


def test_renamed_raw_source_if_uses_its_exact_condition_slot() -> None:
    branch = next(
        node
        for node in _tree(
            "if renamed is sentinel:\n"
            "    assert renamed is sentinel\n"
            "else:\n"
            "    assert renamed is not sentinel\n"
        ).nodes()
        if isinstance(node, If)
    )

    sugar = branch.sugar()
    outcome = sugar.desugar(None)

    slot = branch_result_slot(branch.test)
    assert sugar.branch_slot == slot
    assert isinstance(outcome, Complete)
    assert outcome.value.guard == branch_result_guard(slot, sugar.site)


def test_repeated_raw_source_if_construction_does_not_mint_a_second_slot() -> None:
    branch, _ = _two_ifs()

    first = branch.sugar()
    second = branch.sugar()
    outcome = second.desugar(None)

    assert second is first
    assert isinstance(outcome, Complete)
    authentications = tuple(
        entry
        for entry in outcome.value.unconditional_entries
        if isinstance(entry, BranchResultAuthentication)
    )
    assert len(authentications) == 1
    assert authentications[0].slot == branch_result_slot(branch.test)


def test_condition_owned_slot_constructs_one_authenticated_guard() -> None:
    branch, _ = _two_ifs()
    slot = branch_result_slot(branch.test)
    rewritten = branch._rewrite_with_slot({}, slot)

    sugar = rewritten.sugar()
    outcome = sugar.desugar(None)

    assert sugar.branch_slot == slot
    assert isinstance(outcome, Complete)
    guarded = outcome.value
    assert guarded.guard == branch_result_guard(slot, rewritten.fragment)
    assert len(guarded.unconditional_entries) == 1
    authentication = guarded.unconditional_entries[0]
    assert isinstance(authentication, BranchResultAuthentication)
    assert authentication.slot == slot


def test_nearby_condition_slot_is_rejected_at_the_if_occurrence() -> None:
    branch, nearby = _two_ifs()
    wrong_slot = branch_result_slot(nearby.test)
    rewritten = branch._rewrite_with_slot({}, wrong_slot)

    with pytest.raises(BackendDefect) as raised:
        rewritten.sugar()

    message = str(raised.value)
    assert "If._construct_sugar" in message
    assert "branch-result slot" in message
    assert "if-construct-slot.py:1:0" in message


def test_condition_halt_bypasses_both_if_bodies() -> None:
    source = (
        "def choose(value):\n"
        "    if value < 1:\n"
        "        return 10\n"
        "    else:\n"
        "        return 20\n"
        "\n"
        "choose(None)\n"
    )
    outcomes = tuple(
        node.sugar().desugar(None)
        for node in _tree(source).nodes()
        if isinstance(node, Call)
    )

    assert len(outcomes) == 1
    outcome = outcomes[0]
    assert isinstance(outcome, ExitSet)
    assert len(outcome.exits) == 1
    halted = outcome.exits[0]
    assert isinstance(halted, Halted)
    assert halted.effect.occurrence_id is not None
    assert halted.state is not None


def test_condition_halt_emits_no_occurrence_from_toxic_body_twins() -> None:
    source = (
        "def choose(value):\n"
        "    if value < 1:\n"
        "        return None < 2\n"
        "    else:\n"
        "        return 2 < None\n"
        "\n"
        "choose(None)\n"
    )
    tree = _tree(source)
    comparisons = tuple(node for node in tree.nodes() if isinstance(node, Compare))
    assert len(comparisons) == 3
    (outcome,) = tuple(
        node.sugar().desugar(None)
        for node in tree.nodes()
        if isinstance(node, Call)
    )

    assert isinstance(outcome, ExitSet)
    assert len(outcome.exits) == 1
    halted = outcome.exits[0]
    assert isinstance(halted, Halted)
    condition_occurrence = str(comparisons[0].sugar().site)
    body_occurrences = {str(node.sugar().site) for node in comparisons[1:]}
    assert halted.effect.occurrence_id == condition_occurrence
    assert halted.effect.occurrence_id not in body_occurrences
    assert halted.state is not None


def test_complementary_results_share_only_the_condition_owned_slot() -> None:
    branch, _ = _two_ifs()
    slot = branch_result_slot(branch.test)
    rewritten = branch._rewrite_with_slot({}, slot)

    outcome = rewritten.sugar().desugar(None)

    assert isinstance(outcome, Complete)
    guarded = outcome.value
    expected = branch_result_guard(slot, rewritten.fragment)
    assert guarded.guard == expected
    assert len(guarded.entries) == 2
    then_formula = guarded.entries[0].formula
    else_formula = guarded.entries[1].formula
    assert then_formula.kind == "implies"
    assert then_formula.operands[0] == expected
    assert else_formula.kind == "implies"
    assert else_formula.operands[0].kind == "not"
    assert else_formula.operands[0].operands[0] == expected
    authentications = tuple(
        entry
        for entry in guarded.unconditional_entries
        if isinstance(entry, BranchResultAuthentication)
    )
    assert len(authentications) == 1
    assert authentications[0].slot == slot


def test_identical_condition_spellings_at_distinct_ifs_do_not_share_slots() -> None:
    branches = tuple(
        node
        for node in _tree(
            "if left is right:\n"
            "    assert left is right\n"
            "else:\n"
            "    assert left is not right\n"
            "if left is right:\n"
            "    assert left is right\n"
            "else:\n"
            "    assert left is not right\n"
        ).nodes()
        if isinstance(node, If)
    )
    assert len(branches) == 2

    slots = tuple(branch_result_slot(branch.test) for branch in branches)
    rewritten = tuple(
        branch._rewrite_with_slot({}, slot)
        for branch, slot in zip(branches, slots, strict=True)
    )
    outcomes = tuple(branch.sugar().desugar(None) for branch in rewritten)

    assert slots[0] != slots[1]
    expected_guards = tuple(
        branch_result_guard(slot, branch.fragment)
        for branch, slot in zip(rewritten, slots, strict=True)
    )
    assert expected_guards[0] != expected_guards[1]
    for outcome, slot, expected in zip(
        outcomes, slots, expected_guards, strict=True
    ):
        assert isinstance(outcome, Complete)
        guarded = outcome.value
        assert guarded.guard == expected
        authentications = tuple(
            entry
            for entry in guarded.unconditional_entries
            if isinstance(entry, BranchResultAuthentication)
        )
        assert len(authentications) == 1
        assert authentications[0].slot == slot
