"""Every source ``If`` consumes its one authenticated branch-result slot."""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.caller_parameter_contract import NativeOperationExitCarrierV1
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import GuardedReturn, ReturnValue, TermValue
from sugar_lift_py_tests.ir import not_
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.binding_state import branch_result_slot
from sugar_source_tree.nodes import Call, FunctionDef, If, IfExp
from sugar_source_tree.panic import BackendDefect
from sugar_source_tree.tree import SourceFile


def _tree(source: str) -> SourceFile:
    return SourceFile(
        (source, "if-branch-result-slot.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _only(outcome, kind):
    assert isinstance(outcome, ExitSet)
    assert len(outcome.exits) == 1
    exit_ = outcome.exits[0]
    assert isinstance(exit_, kind)
    return exit_


def test_concrete_if_elif_else_constructs_and_selects_each_reachable_slot() -> None:
    source = ""
    for name, first, second in (
        ("first", True, False),
        ("second", False, True),
        ("fallback", False, False),
    ):
        source += (
            f"def {name}():\n"
            f"    if {first}:\n"
            "        return 10\n"
            f"    elif {second}:\n"
            "        return 20\n"
            "    else:\n"
            "        return 30\n"
        )
    functions = tuple(_tree(source).functions())
    values = []
    for function in functions:
        outcome = function.sugar().desugar(None)
        assert hasattr(outcome, "value")
        returns = tuple(
            entry
            for entry in outcome.value.record.statements
            if isinstance(entry, (ReturnValue, GuardedReturn))
        )
        assert len(returns) == 1, repr(outcome.value.record.statements)
        value = returns[0].value
        assert isinstance(value, TermValue)
        values.append(value.value)

    assert tuple(values) == (10, 20, 30)


def test_undecidable_if_elif_else_retains_complementary_faces() -> None:
    source = (
        "def choose(left, right):\n"
        "    if left < right:\n"
        "        return 10\n"
        "    return 30\n"
    )
    function = next(
        node for node in _tree(source).nodes() if isinstance(node, FunctionDef)
    )
    pending = function.sugar().desugar(None)
    assert isinstance(pending, NativeOperationExitCarrierV1)

    left, right = pending.coordinates
    from sugar_lift_py_tests.floor import SymbolicValue
    from sugar_lift_py_tests.ir import make_var

    exits = pending.discharge(
        {
            left.coordinate_cid: SymbolicValue(make_var("actual_left")),
            right.coordinate_cid: SymbolicValue(make_var("actual_right")),
        }
    )
    assert isinstance(exits, ExitSet)
    completed = _only(exits, Completed)
    returns = tuple(
        entry
        for entry in completed.value.record.statements
        if isinstance(entry, GuardedReturn)
    )
    assert {entry.value for entry in returns} == {
        TermValue(10),
        TermValue(30),
    }
    first_guard = next(entry.guards[0] for entry in returns if entry.value == TermValue(10))
    assert any(
        guard == not_(first_guard)
        for entry in returns
        if entry.value != TermValue(10)
        for guard in entry.guards
    )


def test_condition_halt_bypasses_every_if_elif_else_body() -> None:
    source = (
        "def choose(flag):\n"
        "    if flag < 1:\n"
        "        return 10\n"
        "    else:\n"
        "        return 30\n"
    )
    tree = _tree(f"{source}\nchoose(None)\n")
    (outcome,) = tuple(
        node.sugar().desugar(None)
        for node in tree.nodes()
        if isinstance(node, Call)
    )

    halted = _only(outcome, Halted)
    from sugar_lift_py_tests.temporal.temporal_context import TemporalContext

    expected = TemporalContext.empty().value_for("TypeError")
    assert halted.effect.exception_type_coordinate == expected.exception_type_identity()


def _two_source_ifs() -> tuple[If, If]:
    tree = _tree(
        "if left:\n"
        "    x = 1\n"
        "if right:\n"
        "    y = 2\n"
    )
    branches = tuple(node for node in tree.nodes() if isinstance(node, If))
    assert len(branches) == 2
    return branches


def test_absent_branch_result_slot_panics_at_the_exact_if_occurrence() -> None:
    branch, _ = _two_source_ifs()

    with pytest.raises(BackendDefect) as raised:
        branch.sugar()

    message = str(raised.value)
    assert "If without a stored branch-result slot" in message
    assert "if-branch-result-slot.py:1:0" in message


def test_truthful_stored_slot_constructs_but_slot_swap_panics_at_its_occurrence() -> None:
    truthful, unrelated = _two_source_ifs()
    truthful_slot = branch_result_slot(truthful.test)
    unrelated_slot = branch_result_slot(unrelated.test)

    truthful._rewrite_with_slot({}, truthful_slot).sugar()
    swapped = truthful._rewrite_with_slot({}, unrelated_slot)
    with pytest.raises(BackendDefect) as raised:
        swapped.sugar()

    message = str(raised.value)
    assert "branch-result slot" in message
    assert "if-branch-result-slot.py:1:0" in message


def test_duplicated_branch_result_slot_panics_at_the_exact_if_occurrence() -> None:
    branch, _ = _two_source_ifs()
    slot = branch_result_slot(branch.test)
    duplicated = branch._rewrite_with_slot({}, slot)._rewrite_with_slot({}, slot)

    with pytest.raises(BackendDefect) as raised:
        duplicated.sugar()

    message = str(raised.value)
    assert "branch-result slot" in message
    assert "if-branch-result-slot.py:1:0" in message


def test_symbolic_ternary_result_uses_its_authenticated_branch_slot() -> None:
    from sugar_lift_py_tests.floor.branch_result_coordinate import branch_result_guard
    from sugar_lift_py_tests.floor.guarded_value import GuardedValue

    tree = _tree("def choose(a, b):\n    return 10 if a is b else 20\n")
    ternary = next(node for node in tree.nodes() if isinstance(node, IfExp))
    outcome = ternary.sugar().desugar(None)

    assert hasattr(outcome, "value")
    assert isinstance(outcome.value, GuardedValue)
    assert outcome.value.guard == branch_result_guard(
        branch_result_slot(ternary.test), ternary.fragment
    )


def test_distinct_ternary_occurrences_never_share_a_result_slot() -> None:
    tree = _tree(
        "def choose(a, b):\n"
        "    left = 10 if a is b else 20\n"
        "    right = 30 if a is b else 40\n"
        "    return left + right\n"
    )
    ternaries = tuple(node for node in tree.nodes() if isinstance(node, IfExp))
    assert len(ternaries) == 2

    slots = tuple(branch_result_slot(node.test).slot_id for node in ternaries)
    assert slots[0] != slots[1]


@pytest.mark.parametrize(
    ("kind", "stopping_type"),
    (("And", False), ("Or", True)),
    ids=("and-false", "or-true"),
)
def test_boolean_short_circuit_returns_the_exact_stopping_operand(
    kind: str, stopping_type: bool
) -> None:
    from sugar_lift_py_tests.sugar.bool_op_sugar import BoolOpSugar
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

    literal = TrueBoolLiteralSugar if stopping_type else FalseBoolLiteralSugar
    left = literal("left-occurrence")

    class Skipped:
        def desugar(self, ctx=None):
            raise AssertionError("short-circuited operand was evaluated")

    outcome = BoolOpSugar(kind, (left, Skipped()), "boolop-site").desugar(None)

    assert hasattr(outcome, "value")
    assert outcome.value is left


@pytest.mark.parametrize(
    ("kind", "continuing_type"),
    (("And", True), ("Or", False)),
    ids=("and-true", "or-false"),
)
def test_boolean_continuing_face_returns_the_exact_second_operand(
    kind: str, continuing_type: bool
) -> None:
    from sugar_lift_py_tests.sugar.bool_op_sugar import BoolOpSugar
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

    literal = TrueBoolLiteralSugar if continuing_type else FalseBoolLiteralSugar
    left = literal("left-occurrence")
    right = TermValue(7)

    class Right:
        def desugar(self, ctx=None):
            from sugar_lift_py_tests.outcome import Complete

            return Complete(right)

    outcome = BoolOpSugar(kind, (left, Right()), "boolop-site").desugar(None)

    assert hasattr(outcome, "value")
    assert outcome.value is right
