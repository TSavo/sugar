"""Formal native operations use the one Python call binder."""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.outcome import ExitSet, Halted, NativeOperationExitCarrierV1
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Call, FunctionDef
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _tree(source: str) -> SourceFile:
    return SourceFile(
        (source, "formal_binding.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _call_outcome(signature: str, actuals: str):
    source = (
        f"def helper({signature}):\n"
        "    return left + right\n\n"
        f"helper({actuals})\n"
    )
    tree = _tree(source)
    call = tuple(node for node in tree.nodes() if isinstance(node, Call))[-1]
    return call.sugar().desugar(None)


def _assert_named_halt(outcome) -> None:
    assert isinstance(outcome, ExitSet)
    assert len(outcome.exits) == 1
    halted = outcome.exits[0]
    assert isinstance(halted, Halted)
    assert halted.effect.exception_type_coordinate is not None
    assert halted.effect.occurrence_id is not None


def test_positional_actuals_discharge_through_python_binder() -> None:
    _assert_named_halt(_call_outcome("left, right", "None, 2"))


def test_keyword_actuals_discharge_through_python_binder() -> None:
    _assert_named_halt(_call_outcome("left, right", "left=None, right=2"))


def test_default_actual_is_keyed_to_its_formal_coordinate() -> None:
    _assert_named_halt(_call_outcome("left, right=2", "None"))


def test_wrong_coordinate_actual_cannot_discharge_pending_operation() -> None:
    source = "def helper(left, right):\n    return left + right\n"
    function = next(
        node for node in _tree(source).nodes() if isinstance(node, FunctionDef)
    )
    pending = function.sugar().desugar(None)
    assert isinstance(pending, NativeOperationExitCarrierV1)
    left, right = function.formal_coordinates()

    with pytest.raises(SugarNotWritten, match="caller actual absent"):
        pending.discharge(
            {
                f"wrong:{left.coordinate_cid}": TermValue(1),
                right.coordinate_cid: TermValue(2),
            }
        )
