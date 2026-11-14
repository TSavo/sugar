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
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_py_tests.temporal import bind_temporal
from sugar_source_tree.binding_state import mint_binding_coordinate_v1
from sugar_source_tree.nodes import (
    For,
    FunctionDef,
    TargetPatternConstructionGapV1,
    TargetPatternV1,
)
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.tree import SourceFile


def _function(source: str) -> FunctionDef:
    with TemporaryDirectory(dir=Path.cwd()) as directory:
        path = (
            Path(directory).relative_to(Path.cwd()) / "live_for_destructuring_target.py"
        )
        path.write_text(source)
        tree = SourceFile.from_path(path, construction_context=TreeConstructionContextV1.for_test_without_workspace())
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
    assert isinstance(outcome, ExitSet), outcome
    value = outcome.completed_value()
    if value is not None:
        return value.post()
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


def test_live_assignment_hands_on_its_write_without_writing_the_name() -> None:
    # ``total = total + left`` binds its carried write of ``total``; the next
    # item's header and the publication read that write, never the name.
    source = (
        "def helper():\n"
        "    total = 0\n"
        "    for left, right in [(1, 2), (3, 4)]:\n"
        "        total = total + left\n"
        "    return total\n"
    )

    post = _completed_post(_function(source).sugar().desugar())

    assert post.args[1].value == 4


def test_live_else_reads_the_carried_augmented_value_and_publishes_its_own() -> None:
    # The else reads ``total`` through the header (1 + 3 after the last
    # item), and the read after the loop sees the else's ``+= 10``.
    source = (
        "def helper():\n"
        "    total = 0\n"
        "    for left, right in [(1, 2), (3, 4)]:\n"
        "        total += left\n"
        "    else:\n"
        "        total += 10\n"
        "    return total\n"
    )

    post = _completed_post(_function(source).sugar().desugar())

    assert post.args[1].value == 14


def test_live_post_loop_read_after_else_sees_the_elses_assignment() -> None:
    # ``seen`` is written only by the else, from the carried ``total``.
    source = (
        "def helper():\n"
        "    total = 0\n"
        "    seen = 0\n"
        "    for left, right in [(1, 2), (3, 4)]:\n"
        "        total += left\n"
        "    else:\n"
        "        seen = total\n"
        "    return seen\n"
    )

    post = _completed_post(_function(source).sugar().desugar())

    assert post.args[1].value == 4


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
        carried=(result,),
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


_RUNNING_LOOP = (
    "def helper(items):\n"
    "    total = 5\n"
    "    for left, right in items:\n"
    "        total = total + left\n"
    "    return total\n"
)


def test_live_first_item_reads_the_pre_loop_value_through_its_header() -> None:
    # ``total = 5`` before the loop: the first item's ``total + left`` reads
    # it through the header's key, handed in as what the item carries; the
    # name is never written, so a read of it by name would find nothing.
    source = _RUNNING_LOOP.replace("def helper(items)", "def helper()").replace(
        "in items", "in [(1, 2), (3, 4)]"
    )

    post = _completed_post(_function(source).sugar().desugar())

    assert post.args[1].value == 9


def test_live_item_reads_what_it_carries_with_the_name_unbound() -> None:
    from sugar_lift_py_tests.floor.scope_rebind import ScopeRebind
    from sugar_lift_py_tests.sugar.evaluation_ref_sugar import EvaluationRefSugar

    recurrence = _loop_sugar(_RUNNING_LOOP)
    runtime = recurrence.construction.loop_runtime
    assert runtime.carried_names == ("total",)
    [(header, _writes, _else_writes)] = runtime.carried_evaluations
    [assign] = runtime.body_sugars
    # The body reads ``total`` through the header, not by spelling.
    reads = [
        sugar
        for sugar in (assign.value.left, assign.value.right)
        if isinstance(sugar, EvaluationRefSugar) and sugar.name == "total"
    ]
    assert [read.evaluation for read in reads] == [header]

    ctx = ReduceContext.root(owner="live-pre-loop")
    outcome = recurrence._advance_iterator(
        TupleIteratorValue((TupleValue((TermValue(1), TermValue(2))),)),
        runtime,
        ctx,
        entries=(),
        carried=(TermValue(5),),
    )

    assert isinstance(outcome, ExitSet)
    block = outcome.completed_value()
    assert block is not None, outcome.exits
    [published] = [
        entry for entry in block.statements if isinstance(entry, ScopeRebind)
    ]
    assert published.name == recurrence.binding_coordinate_cids[0]


def test_live_item_handed_nothing_it_carries_is_refused_by_name() -> None:
    from sugar_source_tree.panic import SugarNotWritten

    recurrence = _loop_sugar(_RUNNING_LOOP)
    ctx = bind_temporal(
        ReduceContext.root(owner="live-nothing-carried"),
        "total",
        TermValue(5),
        owner="live-nothing-carried",
        blame=str(recurrence.site),
    )

    # The name holds 5, and is not read in place of what the item carries.
    with pytest.raises(SugarNotWritten):
        recurrence._advance_iterator(
            TupleIteratorValue((TupleValue((TermValue(1), TermValue(2))),)),
            recurrence.construction.loop_runtime,
            ctx,
            entries=(),
            carried=None,
        )


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
        pattern.source_unit.require_target_pattern_coordinates(
            pattern, foreign_site_lie
        )
    assert site_rejected.value.reason == "foreign-target-coordinate"
    assert site_rejected.value.target_pattern is pattern
    assert site_rejected.value.expected_coordinates is pattern.coordinates
    assert site_rejected.value.actual_coordinates is foreign_site_lie

    foreign_scope_lie = (foreign_scope, pattern.target_coordinates[1])
    with pytest.raises(TargetPatternConstructionGapV1) as scope_rejected:
        pattern.source_unit.require_target_pattern_coordinates(
            pattern, foreign_scope_lie
        )
    assert scope_rejected.value.reason == "foreign-target-scope"
    assert scope_rejected.value.target_pattern is pattern
    assert scope_rejected.value.expected_coordinates is pattern.coordinates
    assert scope_rejected.value.actual_coordinates is foreign_scope_lie
