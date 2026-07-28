"""Function formals resume one pending native operation at real callers."""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.context_manager_contract import (
    AuthenticatedRaiseMatcher,
    EffectBoundaryDisposition,
)
from sugar_lift_py_tests.context_manager_resolution import (
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.effect.expectation_not_met_effect import (
    ExpectationNotMetEffect,
)
from sugar_lift_py_tests.floor import DictValue, TermValue, TupleValue
from sugar_lift_py_tests.ir import ctor, str_const
from sugar_lift_py_tests.outcome import (
    Completed,
    ExitSet,
    Halted,
    NativeOperationExitCarrierV1,
)
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Call, FunctionDef
from sugar_source_tree.tree import SourceFile


def _coordinate(node) -> SourceFragmentCoordinateV1:
    span = node.line_col_span()
    return SourceFragmentCoordinateV1(
        node.unit.source_cid,
        span.start_line,
        span.start_col,
        span.end_line,
        span.end_col,
    )


def _tree(source: str) -> tuple[SourceFile, TreeConstructionContextV1]:
    context = TreeConstructionContextV1.for_source_call_construction()
    return (
        SourceFile(
            (source, "formal_resume.py", blake3_512_of(source.encode())),
            construction_context=context,
        ),
        context,
    )


def _helper_and_calls(*calls: str):
    source = (
        "def helper(left, right=2, *rest, **named):\n"
        "    return left < right\n\n" + "".join(f"helper({call})\n" for call in calls)
    )
    tree, context = _tree(source)
    helper = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    frame = helper.source_visible_call_frame()
    call_nodes = tuple(node for node in tree.nodes() if isinstance(node, Call))
    for call in call_nodes:
        context.source_call_frames[_coordinate(call)] = frame
    return helper, frame, call_nodes


def test_helper_alone_retains_undischarged_native_operation() -> None:
    helper, _, _ = _helper_and_calls()
    outcome = helper.sugar().desugar(None)

    assert isinstance(outcome, NativeOperationExitCarrierV1)
    assert all(outcome.demand.operand_coordinate_cids)


def test_existing_binder_keys_keyword_default_and_variadics_by_formal_coordinate():
    _, frame, calls = _helper_and_calls("None, marker=5")
    call = calls[0]
    sugar = call.sugar()
    positional = tuple(arg.desugar(None).value for arg in sugar.args)
    keywords = tuple(
        (name, value.desugar(None).value) for name, value in sugar.keywords
    )

    substitution = frame.bind_formal_actuals(positional, keywords)

    coordinates = frame.projection_formal_coordinates
    assert substitution.by_formal_coordinate[coordinates[0].coordinate_cid].to_term(
        owner="test"
    ) == positional[0].to_term(owner="test")
    assert substitution.by_formal_coordinate[
        coordinates[1].coordinate_cid
    ] == TermValue(2)
    assert isinstance(
        substitution.by_formal_coordinate[coordinates[2].coordinate_cid], TupleValue
    )
    assert isinstance(
        substitution.by_formal_coordinate[coordinates[3].coordinate_cid], DictValue
    )


def test_actual_caller_projects_named_exception_from_operation_floor() -> None:
    _, frame, calls = _helper_and_calls("None")

    outcome = calls[0].sugar().desugar(None)

    assert isinstance(outcome, ExitSet)
    assert len(outcome.exits) == 1
    halted = outcome.exits[0]
    assert isinstance(halted, Halted)
    assert halted.effect.exception_type_coordinate == ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const("TypeError")],
    )
    assert halted.effect.occurrence_id == str(
        frame.pending_native_operation.demand.source_node.wire()
    )


def test_wrong_expected_type_does_not_consume_named_exception() -> None:
    _, frame, calls = _helper_and_calls("None")
    sugar = calls[0].sugar()
    positional = tuple(arg.desugar(None).value for arg in sugar.args)
    substitution = frame.bind_formal_actuals(positional, ())
    discharged = frame.pending_native_operation.discharge(
        substitution.by_formal_coordinate
    )
    outcome = calls[0].sugar().desugar(None)

    assert isinstance(discharged, ExitSet)
    assert isinstance(discharged.exits[0], Halted)
    operation_exception_coordinate = (
        discharged.exits[0].effect.exception_type_coordinate
    )

    class ExpectedValueError:
        def exception_type_identity(self):
            return ctor(
                "python:exception_type_identity",
                [str_const("builtins"), str_const("ValueError")],
            )

    projected = outcome.and_exit(
        ExitSet.completed(object()),
        disposition=EffectBoundaryDisposition(
            matcher=AuthenticatedRaiseMatcher(expected=ExpectedValueError()),
            unmet=ExpectationNotMetEffect("raise", "assertion-site"),
        ),
    )

    assert len(projected.exits) == 1
    assert isinstance(projected.exits[0], Halted)
    assert (
        projected.exits[0].effect.exception_type_coordinate
        == operation_exception_coordinate
    )
    assert projected.exits[0].effect.exception_type_coordinate != (
        ExpectedValueError().exception_type_identity()
    )


def test_normal_actuals_project_completed() -> None:
    _, _, calls = _helper_and_calls("1")

    outcome = calls[0].sugar().desugar(None)

    assert isinstance(outcome, ExitSet)
    assert len(outcome.exits) == 1
    assert isinstance(outcome.exits[0], Completed)


def test_unresolved_actual_retains_undischarged_demand() -> None:
    _, frame, calls = _helper_and_calls("unknown")

    outcome = calls[0].sugar().desugar(None)

    assert outcome is frame.pending_native_operation


def test_pending_operation_uses_floor_binder_once_not_node_rebinding(
    monkeypatch,
) -> None:
    _, _, calls = _helper_and_calls("None")

    def duplicate_mapper(*args, **kwargs):
        del args, kwargs
        raise AssertionError(
            "pending native operation entered a second argument mapper"
        )

    from sugar_lift_py_tests.source_call_frame import SourceVisibleCallFrameV1

    original_bind_actuals = SourceVisibleCallFrameV1.bind_actuals
    calls_to_binder = 0

    def counted_binder(self, positional, keywords, ctx=None):
        nonlocal calls_to_binder
        calls_to_binder += 1
        return original_bind_actuals(self, positional, keywords, ctx)

    monkeypatch.setattr(SourceVisibleCallFrameV1, "bind_node_actuals", duplicate_mapper)
    monkeypatch.setattr(SourceVisibleCallFrameV1, "bind_actuals", counted_binder)

    outcome = calls[0].sugar().desugar(None)
    assert isinstance(outcome, ExitSet)
    assert calls_to_binder == 1


def test_caller_resumes_stored_operation_without_redesugaring_function(
    monkeypatch,
) -> None:
    _, _, calls = _helper_and_calls("None")

    from sugar_lift_py_tests.sugar.function_universe_sugar import FunctionUniverseSugar

    def reconstructed(*args, **kwargs):
        del args, kwargs
        raise AssertionError("caller re-desugared the FunctionDef")

    monkeypatch.setattr(FunctionUniverseSugar, "desugar", reconstructed)

    outcome = calls[0].sugar().desugar(None)
    assert isinstance(outcome, ExitSet)
    assert isinstance(outcome.exits[0], Halted)
