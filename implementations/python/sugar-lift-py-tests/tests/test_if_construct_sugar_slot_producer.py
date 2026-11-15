"""The source ``If`` producer must supply one condition-owned result slot.

An undecided condition is read off a function's formals: a module-level read
of a name nothing binds is Python's ``NameError`` at the condition, which the
lifter answers, so a condition over free module names never reaches its
branches at all."""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor.branch_result_coordinate import (
    BranchResultAuthentication,
    branch_result_guard,
)
from sugar_lift_py_tests.outcome import ExitSet, Halted
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
            "def decide(left, right, nearby):\n"
            "    if left is right:\n"
            "        assert left is right\n"
            "    else:\n"
            "        assert left is not right\n"
            "    if nearby:\n"
            "        pass\n"
        ).nodes()
        if isinstance(node, If)
    )
    assert len(branches) == 2
    return branches


def test_a_condition_over_free_module_names_is_python_s_name_error() -> None:
    """Nothing binds ``left`` at module level: Python raises ``NameError`` at
    the condition, before either branch runs, and so does the lifter."""
    branch = next(
        node
        for node in _tree(
            "if left is right:\n"
            "    assert left is right\n"
            "else:\n"
            "    assert left is not right\n"
        ).nodes()
        if isinstance(node, If)
    )

    outcome = branch.sugar().desugar(None)

    assert outcome.completed_value() is None
    assert outcome.halts() == outcome.exits
    (halt,) = outcome.halts()
    assert halt.effect.exception_name == "NameError"
    assert halt.effect.name == "left"


def test_raw_source_if_routes_through_one_condition_owned_slot() -> None:
    branch, _ = _two_ifs()

    sugar = branch.sugar()
    outcome = sugar.desugar(None)

    slot = branch_result_slot(branch.test)
    assert sugar.branch_slot == slot
    assert outcome.completed_value() is not None
    authentications = tuple(
        entry
        for entry in outcome.completed_value().unconditional_entries
        if isinstance(entry, BranchResultAuthentication)
    )
    assert len(authentications) == 1
    assert authentications[0].slot == slot


def test_renamed_raw_source_if_uses_its_exact_condition_slot() -> None:
    branch = next(
        node
        for node in _tree(
            "def decide(renamed, sentinel):\n"
            "    if renamed is sentinel:\n"
            "        assert renamed is sentinel\n"
            "    else:\n"
            "        assert renamed is not sentinel\n"
        ).nodes()
        if isinstance(node, If)
    )

    sugar = branch.sugar()
    outcome = sugar.desugar(None)

    slot = branch_result_slot(branch.test)
    assert sugar.branch_slot == slot
    assert outcome.completed_value() is not None
    # The arms are guarded by the test's own condition, the formula the slot
    # is authenticated as -- never by the slot (#7757).
    guarded = outcome.completed_value()
    (authentication,) = tuple(
        entry
        for entry in guarded.unconditional_entries
        if isinstance(entry, BranchResultAuthentication)
    )
    assert authentication.slot == slot
    assert guarded.guard == authentication.observed_guard
    assert guarded.guard != branch_result_guard(slot, sugar.site)


def test_repeated_raw_source_if_construction_does_not_mint_a_second_slot() -> None:
    branch, _ = _two_ifs()

    first = branch.sugar()
    second = branch.sugar()
    outcome = second.desugar(None)

    assert second is first
    assert outcome.completed_value() is not None
    authentications = tuple(
        entry
        for entry in outcome.completed_value().unconditional_entries
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
    assert outcome.completed_value() is not None
    guarded = outcome.completed_value()
    assert len(guarded.unconditional_entries) == 1
    authentication = guarded.unconditional_entries[0]
    assert isinstance(authentication, BranchResultAuthentication)
    assert authentication.slot == slot
    # The slot is authenticated as the test's condition, and the arms are
    # guarded by that condition itself.
    assert guarded.guard == authentication.observed_guard
    assert guarded.guard != branch_result_guard(slot, rewritten.fragment)


def test_nearby_condition_slot_is_rejected_at_the_if_occurrence() -> None:
    branch, nearby = _two_ifs()
    wrong_slot = branch_result_slot(nearby.test)
    rewritten = branch._rewrite_with_slot({}, wrong_slot)

    with pytest.raises(BackendDefect) as raised:
        rewritten.sugar()

    message = str(raised.value)
    assert "If._construct_sugar" in message
    assert "branch-result slot" in message
    assert "if-construct-slot.py:2:4" in message


def _call_and_callee(source: str):
    """``choose(None)`` and ``choose``'s own reduction.

    #7757 step 5 (#8705, "Edge, join at prove"): the call is its coordinate
    and edge, the one unanswered call (completes under its
    ``python:unknown_callee_call.completes`` atom, halts under the complement
    with nothing named), never ``choose``'s body applied to ``None``.  What
    the body does with ``None`` is stated by ``choose``'s contract over its
    formal and decided at prove: its reduction is the condition's carrier,
    pending on ``value < 1`` before either branch is entered, so a halt of the
    condition is stated ahead of both bodies."""
    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )
    from sugar_lift_py_tests.effect import UndeterminedRaiseEffect
    from sugar_source_tree.nodes import FunctionDef

    tree = _tree(source)
    (outcome,) = tuple(
        node.sugar().desugar(None) for node in tree.nodes() if isinstance(node, Call)
    )
    assert isinstance(outcome, ExitSet)
    assert len(outcome.exits) == 2
    (halted,) = outcome.halts()
    assert isinstance(halted, Halted)
    assert type(halted.effect) is UndeterminedRaiseEffect
    assert halted.effect.exception_name is None
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    pending = function.sugar().desugar(None)
    assert isinstance(pending, NativeOperationExitCarrierV1)
    assert pending.demand.operator == "less_than"
    return tree, outcome, halted


def test_condition_halt_bypasses_both_if_bodies() -> None:
    _call_and_callee(
        "def choose(value):\n"
        "    if value < 1:\n"
        "        return 10\n"
        "    else:\n"
        "        return 20\n"
        "\n"
        "choose(None)\n"
    )


def test_condition_halt_emits_no_occurrence_from_toxic_body_twins() -> None:
    tree, outcome, halted = _call_and_callee(
        "def choose(value):\n"
        "    if value < 1:\n"
        "        return None < 2\n"
        "    else:\n"
        "        return 2 < None\n"
        "\n"
        "choose(None)\n"
    )
    comparisons = tuple(node for node in tree.nodes() if isinstance(node, Compare))
    assert len(comparisons) == 3

    def address(site) -> str:
        return f"{site.filename}:{site.line}:{site.col}"

    body_addresses = {address(node.sugar().site) for node in comparisons[1:]}
    # The call's own halt is raised at the call, never at a body comparison:
    # nothing of ``choose``'s body is read at the call.
    assert not any(body in repr(outcome) for body in body_addresses)
    assert halted.effect.exception_name is None


def test_complementary_results_are_the_two_faces_of_the_test() -> None:
    # Each arm is guarded by the test's own condition, the then arm by it and
    # the else arm by its negation: the arms are exactly the two faces of the
    # test, never of the slot no input decides (#7757).
    branch, _ = _two_ifs()
    slot = branch_result_slot(branch.test)
    rewritten = branch._rewrite_with_slot({}, slot)

    outcome = rewritten.sugar().desugar(None)

    assert outcome.completed_value() is not None
    guarded = outcome.completed_value()
    authentications = tuple(
        entry
        for entry in guarded.unconditional_entries
        if isinstance(entry, BranchResultAuthentication)
    )
    assert len(authentications) == 1
    assert authentications[0].slot == slot
    expected = authentications[0].observed_guard
    assert expected != branch_result_guard(slot, rewritten.fragment)
    assert guarded.guard == expected
    assert len(guarded.entries) == 2
    then_formula = guarded.entries[0].formula
    else_formula = guarded.entries[1].formula
    assert then_formula.kind == "implies"
    assert then_formula.operands[0] == expected
    assert else_formula.kind == "implies"
    assert else_formula.operands[0].kind == "not"
    assert else_formula.operands[0].operands[0] == expected


def test_identical_condition_spellings_at_distinct_ifs_do_not_share_slots() -> None:
    branches = tuple(
        node
        for node in _tree(
            "def decide(left, right):\n"
            "    if left is right:\n"
            "        assert left is right\n"
            "    else:\n"
            "        assert left is not right\n"
            "    if left is right:\n"
            "        assert left is right\n"
            "    else:\n"
            "        assert left is not right\n"
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
    slot_guards = tuple(
        branch_result_guard(slot, branch.fragment)
        for branch, slot in zip(rewritten, slots, strict=True)
    )
    assert slot_guards[0] != slot_guards[1]
    for outcome, slot in zip(outcomes, slots, strict=True):
        assert outcome.completed_value() is not None
        guarded = outcome.completed_value()
        authentications = tuple(
            entry
            for entry in guarded.unconditional_entries
            if isinstance(entry, BranchResultAuthentication)
        )
        assert len(authentications) == 1
        assert authentications[0].slot == slot
        # Each ``if``'s arms are guarded by its own test's condition; the
        # slots, not the guards, tell the two ``if``s apart.
        assert guarded.guard == authentications[0].observed_guard


def test_ground_true_if_does_not_authenticate_an_unused_slot() -> None:
    """A folded ``if True`` does not publish BranchResultAuthentication.

    Ground conditions already guard the selected arm with true_guard/false_guard
    rather than the branch-result slot. Authenticating that unused slot would
    inject term-less testimony into every folded factory ``if not args:``.
    """
    branch = next(
        node
        for node in _tree("if True:\n    pass\n").nodes()
        if isinstance(node, If)
    )

    outcome = branch.sugar().desugar(None)

    assert outcome.completed_value() is not None
    authentications = tuple(
        entry
        for entry in outcome.completed_value().unconditional_entries
        if isinstance(entry, BranchResultAuthentication)
    )
    assert authentications == ()



def test_ground_false_if_records_branch_result_for_the_phi() -> None:
    """A folded ``if False`` still tells the assignment phi which arm lived.

    Substitute emits ``x = <then> if <BranchResultRef> else <else>`` after the
    if. The if itself no longer publishes BranchResultAuthentication when the
    condition is ground (#7487). Recording the folded bool on the reduce
    context lets the phi drop the dead arm instead of evaluating it.
    """
    from sugar_lift_py_tests.context.reduce_context import ReduceContext
    from sugar_lift_py_tests.sugar.branch_result_ref_sugar import BranchResultRefSugar
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar

    branch = next(
        node
        for node in _tree("if False:\n    pass\n").nodes()
        if isinstance(node, If)
    )
    ctx = ReduceContext.root(owner="test")
    sugar = branch.sugar()
    outcome = sugar.desugar(ctx)

    assert outcome.completed_value() is not None
    authentications = tuple(
        entry
        for entry in outcome.completed_value().unconditional_entries
        if isinstance(entry, BranchResultAuthentication)
    )
    assert authentications == ()
    bound = ctx.ground_branch_results[sugar.branch_slot.slot_id]
    assert isinstance(bound, FalseBoolLiteralSugar)
    resolved = BranchResultRefSugar(
        slot=sugar.branch_slot, site=branch.fragment
    ).desugar(ctx)
    assert resolved.completed_value() is not None
    assert isinstance(resolved.completed_value(), FalseBoolLiteralSugar)
