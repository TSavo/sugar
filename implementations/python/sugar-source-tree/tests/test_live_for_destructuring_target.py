"""Authenticated live ``for`` destructuring target recurrence law."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
from sugar_lift_py_tests.context.reduce_context import ReduceContext
from sugar_lift_py_tests.floor.iterator_value import TupleIteratorValue
from sugar_lift_py_tests.floor.term_value import TermValue
from sugar_lift_py_tests.floor.tuple_value import TupleValue
from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet, Halted
from sugar_lift_py_tests.temporal import bind_temporal
from sugar_source_tree.binding_state import mint_binding_coordinate_v1
from sugar_source_tree.nodes import For, FunctionDef, TargetPatternConstructionGapV1, TargetPatternV1
from sugar_source_tree.tree import SourceFile


def _function(source: str) -> FunctionDef:
    with TemporaryDirectory(dir=Path.cwd()) as directory:
        path = Path(directory).relative_to(Path.cwd()) / "live_for_destructuring_target.py"
        path.write_text(source)
        tree = SourceFile.from_path(path)
        return next(node for node in tree.nodes() if isinstance(node, FunctionDef))


def _loop_and_runtime(source: str):
    function = _function(source)
    loop_node = next(node for node in function.body if isinstance(node, For))
    loop_sugar = next(
        statement
        for statement in function.sugar().statements
        if type(statement).__name__ == "LoopRecurrenceSugar"
    )
    return loop_node, loop_sugar.construction.loop_runtime


def _loop_sugar(source: str):
    return next(
        statement
        for statement in _function(source).sugar().statements
        if type(statement).__name__ == "LoopRecurrenceSugar"
    )


def _completed_post(outcome):
    if isinstance(outcome, Complete):
        return outcome.value.post()
    assert isinstance(outcome, ExitSet), outcome
    completed = [face for face in outcome.exits if isinstance(face, Completed)]
    assert len(completed) == 1, completed
    return completed[0].value.post()


_PAIR_LOOP = (
    "def helper(items):\n"
    "    result = 0\n"
    "    for left, right in items:\n"
    "        result = left\n"
    "    return result\n"
)


def test_live_pair_target_retains_producer_coordinates_in_source_order() -> None:
    loop, runtime = _loop_and_runtime(_PAIR_LOOP)

    assert isinstance(runtime.target_pattern, TargetPatternV1)
    assert (
        runtime.target_pattern.target.fragment.seal().cid
        == loop.target.fragment.seal().cid
    )
    assert runtime.target_pattern.target_names == ("left", "right")
    assert tuple(
        coordinate.projection_path
        for coordinate in runtime.target_pattern.target_coordinates
    ) == (("target", 0), ("target", 1))
    assert all(
        coordinate.scope_owner_cid == loop.owned_loop_target.target_cid
        for coordinate in runtime.target_pattern.target_coordinates
    )


def test_live_pair_target_unpacks_by_floor_order_and_threads_each_iteration() -> None:
    source = (
        "def helper():\n"
        "    result = 0\n"
        "    for left, right in [(1, 2), (3, 4)]:\n"
        "        result = left\n"
        "    return result\n"
    )

    post = _completed_post(_function(source).sugar().desugar())

    assert post.args[1].value == 3


def test_live_pair_target_arity_halt_retains_exact_pre_assignment_state() -> None:
    recurrence = _loop_sugar(_PAIR_LOOP)
    result = TermValue(7)
    ctx = bind_temporal(
        ReduceContext.root(owner="live-pair-arity"),
        "result",
        result,
        owner="live-pair-arity",
        blame=str(recurrence.site),
    )

    outcome = recurrence._advance_iterator(
        TupleIteratorValue((TupleValue((TermValue(1),)),)),
        recurrence.construction.loop_runtime,
        ctx,
        entries=(),
    )

    assert isinstance(outcome, ExitSet)
    halted = [face for face in outcome.exits if isinstance(face, Halted)]
    assert len(halted) == 1
    assert isinstance(halted[0].effect, RaiseEffect)
    assert halted[0].effect.exception_name == "ValueError"
    assert halted[0].state is ctx
    assert halted[0].state.temporal.value_if_bound("result") is result
    assert halted[0].state.temporal.value_if_bound("left") is None
    assert halted[0].state.temporal.value_if_bound("right") is None


def test_live_pair_target_rejects_reordered_coordinates() -> None:
    _loop, runtime = _loop_and_runtime(_PAIR_LOOP)
    pattern = runtime.target_pattern

    lied = tuple(reversed(pattern.target_coordinates))
    with pytest.raises(TargetPatternConstructionGapV1) as rejected:
        pattern.source_unit.require_target_pattern_coordinates(pattern, lied)
    assert rejected.value.reason == "target-coordinate-order-mismatch"
    assert rejected.value.target_pattern is pattern
    assert rejected.value.expected_coordinates is pattern.coordinates
    assert rejected.value.actual_coordinates is lied


def test_live_pair_target_rejects_missing_or_extra_coordinates() -> None:
    loop, runtime = _loop_and_runtime(_PAIR_LOOP)
    pattern = runtime.target_pattern
    extra = mint_binding_coordinate_v1(
        scope_owner_cid=loop.owned_loop_target.target_cid,
        binding_site=loop.target.elts[0].fragment,
        projection_path=("target", 2),
    )

    missing = pattern.target_coordinates[:-1]
    with pytest.raises(TargetPatternConstructionGapV1) as missing_rejected:
        pattern.source_unit.require_target_pattern_coordinates(pattern, missing)
    assert missing_rejected.value.reason == "target-coordinate-arity-mismatch"
    assert missing_rejected.value.expected_coordinates is pattern.coordinates
    assert missing_rejected.value.actual_coordinates is missing

    added = (*pattern.target_coordinates, extra)
    with pytest.raises(TargetPatternConstructionGapV1) as extra_rejected:
        pattern.source_unit.require_target_pattern_coordinates(pattern, added)
    assert extra_rejected.value.reason == "target-coordinate-arity-mismatch"
    assert extra_rejected.value.expected_coordinates is pattern.coordinates
    assert extra_rejected.value.actual_coordinates is added


def test_live_pair_target_rejects_foreign_target_and_scope_testimony() -> None:
    loop, runtime = _loop_and_runtime(_PAIR_LOOP)
    pattern = runtime.target_pattern
    foreign_loop, _foreign_runtime = _loop_and_runtime(
        _PAIR_LOOP.replace("left, right", "other_left, other_right")
    )
    foreign_site = mint_binding_coordinate_v1(
        scope_owner_cid=loop.owned_loop_target.target_cid,
        binding_site=foreign_loop.target.elts[0].fragment,
        projection_path=("target", 0),
    )
    foreign_scope = mint_binding_coordinate_v1(
        scope_owner_cid=foreign_loop.owned_loop_target.target_cid,
        binding_site=loop.target.elts[0].fragment,
        projection_path=("target", 0),
    )

    foreign_site_lie = (foreign_site, pattern.target_coordinates[1])
    with pytest.raises(TargetPatternConstructionGapV1) as site_rejected:
        pattern.source_unit.require_target_pattern_coordinates(pattern, foreign_site_lie)
    assert site_rejected.value.reason == "foreign-target-coordinate"
    assert site_rejected.value.target_pattern is pattern
    assert site_rejected.value.expected_coordinates is pattern.coordinates
    assert site_rejected.value.actual_coordinates is foreign_site_lie

    foreign_scope_lie = (foreign_scope, pattern.target_coordinates[1])
    with pytest.raises(TargetPatternConstructionGapV1) as scope_rejected:
        pattern.source_unit.require_target_pattern_coordinates(pattern, foreign_scope_lie)
    assert scope_rejected.value.reason == "foreign-target-scope"
    assert scope_rejected.value.target_pattern is pattern
    assert scope_rejected.value.expected_coordinates is pattern.coordinates
    assert scope_rejected.value.actual_coordinates is foreign_scope_lie
