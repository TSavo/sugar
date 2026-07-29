from __future__ import annotations

import pytest

from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.context_manager_resolution import (
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.floor import TupleValue
from sugar_lift_py_tests.generator_construction import (
    FormalFloorBindingGap,
    FormalFloorBindingV1,
    GeneratorConstructionV1,
    ProjectedFormalFloorBindingV1,
)
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.call_site_sugar import CallSiteSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
from sugar_source_tree.nodes import Call, FunctionDef
from sugar_source_tree.tree import SourceFile
from sugar_lift_python_source.canonical import blake3_512_of


def _frame(tmp_path, monkeypatch, filename: str, function_name: str):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / filename
    path.write_text(
        f"def {function_name}(*args):\n"
        "    if args[0]:\n"
        "        yield 1\n"
        f"{function_name}(True)\n"
    )
    source = path.read_text()
    construction = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (source, path.name, blake3_512_of(source.encode())),
        construction_context=construction,
    )
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    call = next(node for node in tree.nodes() if isinstance(node, Call))
    frame = function.source_visible_call_frame().bind_node_actuals(call.args, ())
    span = call.line_col_span()
    construction.source_call_frames[
        SourceFragmentCoordinateV1(
            call.unit.source_cid,
            span.start_line,
            span.start_col,
            span.end_line,
            span.end_col,
        )
    ] = frame
    return frame, call


def test_vararg_binder_publishes_exact_child_floor_to_generator(tmp_path, monkeypatch):
    frame, call = _frame(tmp_path, monkeypatch, "truth.py", "option_context")
    actual = TrueBoolLiteralSugar(site=call.args[0].fragment)
    bound = frame.bind_actuals((actual,), ())
    child = frame.formal_coordinates[0].project("variadic", 0)

    assert bound.actuals == (TupleValue((actual,)),)
    assert bound.projected_pairs[0].coordinate == child
    assert bound.projected_pairs[0].actual is actual

    outcome = CallSiteSugar(
        target_name="option_context",
        args=(actual,),
        site=call.fragment,
        source_call_frame=frame,
    ).desugar(ReduceContext.root(owner="variadic-child"))
    assert isinstance(outcome, Complete)
    machine = outcome.value
    assert machine._guard_evaluation_context().temporal.value_if_bound(child.cid) is actual


def test_foreign_root_child_projection_refuses_generator_allocation(tmp_path, monkeypatch):
    frame, call = _frame(tmp_path, monkeypatch, "truth.py", "option_context")
    foreign, _ = _frame(tmp_path, monkeypatch, "foreign.py", "other")
    actual = TrueBoolLiteralSugar(site=call.args[0].fragment)
    root = frame.formal_coordinates[0]

    with pytest.raises(FormalFloorBindingGap, match="authenticated variadic child"):
        GeneratorConstructionV1.allocate(
            allocation_coordinate="foreign-child",
            frame_coordinate=frame.frame_cid,
            binding_state=frame.runtime_entries,
            steps=frame.generator_steps,
            formal_floor_bindings=(
                FormalFloorBindingV1(root.cid, TupleValue((actual,))),
            ),
            projected_formal_floor_bindings=(
                ProjectedFormalFloorBindingV1(
                    foreign.formal_coordinates[0].project("variadic", 0), actual
                ),
            ),
        )
