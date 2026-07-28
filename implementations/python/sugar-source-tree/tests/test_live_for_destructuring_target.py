"""Authenticated live ``for`` destructuring target recurrence law."""

from __future__ import annotations

from dataclasses import replace

import pytest

from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
from sugar_lift_py_tests.context.reduce_context import ReduceContext
from sugar_lift_py_tests.floor.iterator_value import TupleIteratorValue
from sugar_lift_py_tests.floor.term_value import TermValue
from sugar_lift_py_tests.floor.tuple_value import TupleValue
from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet, Halted
from sugar_lift_py_tests.temporal import bind_temporal
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.binding_state import mint_binding_coordinate_v1
from sugar_source_tree.live_loop_construction import LiveForTargetPatternV1
from sugar_source_tree.nodes import For, FunctionDef
from sugar_source_tree.tree import SourceFile


def _function(source: str) -> FunctionDef:
    tree = SourceFile(
        (source, "tests/live_for_destructuring_target.py", blake3_512_of(source.encode()))
    )
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

    assert isinstance(runtime.target_pattern, LiveForTargetPatternV1)
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

    with pytest.raises(TypeError, match="source target order"):
        replace(pattern, target_coordinates=tuple(reversed(pattern.target_coordinates)))


def test_live_pair_target_rejects_missing_or_extra_coordinates() -> None:
    loop, runtime = _loop_and_runtime(_PAIR_LOOP)
    pattern = runtime.target_pattern
    extra = mint_binding_coordinate_v1(
        scope_owner_cid=loop.owned_loop_target.target_cid,
        binding_site=loop.target.elts[0].fragment,
        projection_path=("target", 2),
    )

    with pytest.raises(TypeError, match="one coordinate per target leaf"):
        replace(pattern, target_coordinates=pattern.target_coordinates[:-1])
    with pytest.raises(TypeError, match="one coordinate per target leaf"):
        replace(pattern, target_coordinates=(*pattern.target_coordinates, extra))


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

    with pytest.raises(TypeError, match="source target coordinate"):
        replace(
            pattern,
            target_coordinates=(foreign_site, pattern.target_coordinates[1]),
        )
    with pytest.raises(TypeError, match="loop target scope"):
        replace(
            pattern,
            target_coordinates=(foreign_scope, pattern.target_coordinates[1]),
        )
