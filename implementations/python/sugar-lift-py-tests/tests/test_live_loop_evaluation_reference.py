"""Reads in live loops and class bodies are references to their binding
statements' evaluations (temporal choice 1, #7661; item 7).

#7886 rewrote a read after ``x += e`` to ``EvaluationRef`` and keyed each
unrolled iteration's evaluation apart.  A live loop is constructed once and
reduced once per item, so:

- each item's evaluation of a body statement is its own key at reduce
  (``evaluation_here``: the construct-time key qualified by the live items
  around it);
- the body reads a carried name through the loop header's evaluation of it,
  bound per item by the recurrence, instead of the bare name;
- the value an item hands to the next one (the latch) is the latest of the
  header and every write of the name in the body, each bound under its own
  key (``x += e`` its evaluation, an assignment its carried write); the name
  itself is never written;
- the ``else`` suite reads a carried name through the same header, bound
  once more after the last item, and the loop leaves with the latest of the
  else's writes and that header.

A class body and a module block are threaded by substitution, so their reads
after ``x += e`` are references too.  (The export prefix, the third reader
#7886 named, went in #7896.)
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import SymbolicValue, TermValue
from sugar_lift_py_tests.floor.scope_rebind import ScopeRebind
from sugar_lift_py_tests.effect import SequenceUnpackRuntimeEffect
from sugar_lift_py_tests.ir import atomic, ctor, make_var, not_, num, str_const
from sugar_lift_py_tests.occurrence import (
    entered,
    live_iterations,
    loop_iteration_segment,
    loop_symbolic_item_segment,
    occurrence_path,
)
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_py_tests.sugar.assign_sugar import AssignSugar
from sugar_lift_py_tests.sugar.assigned_value import carried_write_key
from sugar_lift_py_tests.sugar.augassign_sugar import AugAssignSugar
from sugar_lift_py_tests.sugar.evaluation_ref_sugar import (
    EvaluationRefSugar,
    evaluation_here,
)
from sugar_lift_py_tests.sugar.loop_recurrence_sugar import (
    LoopBindingRefSugar,
    LoopRecurrenceSugar,
)
from sugar_lift_py_tests.temporal.temporal_context import (
    EVALUATION_PREFIX,
    projection_key,
)
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.live_loop_construction import LiveWhileRuntimeV1
from sugar_source_tree.nodes import (
    Assign,
    AugAssign,
    ClassDef,
    EvaluationRef,
    FunctionDef,
    Return,
    Tuple_,
)
from sugar_source_tree.tree import SourceFile

KEY = EVALUATION_PREFIX + "blake3-512:test-evaluation"
HEADER = EVALUATION_PREFIX + "blake3-512:test-header"
LATCH = EVALUATION_PREFIX + "blake3-512:test-latch"
WRITE = EVALUATION_PREFIX + "blake3-512:test-write"
ELSE_WRITE = EVALUATION_PREFIX + "blake3-512:test-else-write"
POST = EVALUATION_PREFIX + "blake3-512:test-post-binding"
LOOP = "blake3-512:test-loop"


def _source(source: str) -> SourceFile:
    return SourceFile(
        (source, "live_loop_evaluation.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _function(source: str) -> FunctionDef:
    return next(
        node for node in _source(source).nodes() if isinstance(node, FunctionDef)
    )


def _item(index: int) -> str:
    return loop_iteration_segment(LOOP, index)


def _recurrence() -> LoopRecurrenceSugar:
    return LoopRecurrenceSugar(
        target_cid=LOOP,
        loop_construction_cid="blake3-512:test-construction",
        binding_coordinate_cids=(),
        post_binding_keys=(),
        outward_faces=(),
        construction=None,
        site="live-loop-evaluation",
    )


_RUNTIME = SimpleNamespace(
    carried_names=("t",), carried_evaluations=((HEADER, (LATCH,), ()),)
)


# -- one key per live item ---------------------------------------------------


def test_outside_a_live_item_the_key_is_the_construct_time_key() -> None:
    assert evaluation_here(KEY) == KEY


def test_inside_a_live_item_the_key_names_the_item() -> None:
    with entered(_item(0)):
        assert evaluation_here(KEY) == f"{KEY}@{_item(0)}"
        with entered(loop_iteration_segment("blake3-512:inner-loop", 3)):
            inner = loop_iteration_segment("blake3-512:inner-loop", 3)
            assert evaluation_here(KEY) == f"{KEY}@{_item(0)}/{inner}"


def test_an_unrolled_copy_or_a_frame_is_not_a_live_item() -> None:
    # An unrolled copy carries its iteration in its construct-time key; a
    # frame's statements are read inside the frame.
    with occurrence_path(("loop[3,9)#0", "call:python:m.f")):
        assert live_iterations() == ()
        assert evaluation_here(KEY) == KEY


def test_a_reference_reads_its_own_items_evaluation() -> None:
    ctx = ReduceContext.root(owner="live-evaluation")
    ctx = ctx.with_temporal(ctx.temporal.bind_value(f"{KEY}@{_item(0)}", TermValue(1)))
    ctx = ctx.with_temporal(ctx.temporal.bind_value(f"{KEY}@{_item(1)}", TermValue(2)))
    ref = EvaluationRefSugar(evaluation=KEY, name="x", site=None)
    with entered(_item(0)):
        assert ref.desugar(ctx) == ExitSet.completed(TermValue(1))
    with entered(_item(1)):
        assert ref.desugar(ctx) == ExitSet.completed(TermValue(2))


# -- the header: what an item begins with ------------------------------------


def test_each_item_binds_its_own_header() -> None:
    recurrence = _recurrence()
    ctx = ReduceContext.root(owner="live-header")
    with entered(_item(0)):
        ctx = recurrence._enter_header(_RUNTIME, ctx, (TermValue(1),))
    with entered(_item(1)):
        ctx = recurrence._enter_header(_RUNTIME, ctx, (TermValue(2),))
    ref = EvaluationRefSugar(evaluation=HEADER, name="t", site=None)
    with entered(_item(0)):
        assert ref.desugar(ctx) == ExitSet.completed(TermValue(1))
    with entered(_item(1)):
        assert ref.desugar(ctx) == ExitSet.completed(TermValue(2))


def test_a_runtime_naming_no_header_binds_none() -> None:
    recurrence = _recurrence()
    runtime = SimpleNamespace(
        carried_names=("v",), carried_evaluations=((None, (), ()),)
    )
    ctx = ReduceContext.root(owner="live-header")
    with entered(_item(0)):
        entered_ctx = recurrence._enter_header(runtime, ctx, (TermValue(1),))
    assert entered_ctx.temporal.evaluations() == ()


# -- the target: each item's projection, under its key -----------------------

TARGET = EVALUATION_PREFIX + "blake3-512:test-target"
TARGET_COORDINATE = "blake3-512:test-target-coordinate"


def _target_runtime(carried: bool):
    pattern = SimpleNamespace(names=("v",))
    if carried:
        return SimpleNamespace(
            target_pattern=pattern,
            target_evaluations=(TARGET,),
            carried_names=("v",),
            carried_evaluations=((TARGET, (), ()),),
        )
    return SimpleNamespace(
        target_pattern=pattern,
        target_evaluations=(TARGET,),
        carried_names=(),
        carried_evaluations=(),
    )


def test_each_item_reads_its_own_target_never_the_name() -> None:
    recurrence = _recurrence()
    runtime = _target_runtime(carried=False)
    ctx = ReduceContext.root(owner="live-target")
    with entered(_item(0)):
        ctx, bound = recurrence._enter_target(
            runtime, ctx, (("v", TARGET_COORDINATE, TermValue(5)),)
        )
        assert bound == ((evaluation_here(TARGET), TARGET_COORDINATE, TermValue(5)),)
    with entered(_item(1)):
        ctx, _bound = recurrence._enter_target(
            runtime, ctx, (("v", TARGET_COORDINATE, TermValue(6)),)
        )
    assert ctx.temporal.value_if_bound("v") is None
    ref = EvaluationRefSugar(evaluation=TARGET, name="v", site=None)
    with entered(_item(0)):
        assert ref.desugar(ctx) == ExitSet.completed(TermValue(5))
    with entered(_item(1)):
        assert ref.desugar(ctx) == ExitSet.completed(TermValue(6))


def test_a_carried_target_hands_on_its_projection_not_the_name() -> None:
    # The header (what the previous item handed on) is bound first, the
    # item's projection after it under the same key; the name is not read.
    recurrence = _recurrence()
    runtime = _target_runtime(carried=True)
    ctx = ReduceContext.root(owner="live-target-latch")
    ctx = ctx.with_temporal(ctx.temporal.bind_value("v", TermValue(99)))
    with entered(_item(0)):
        ctx = recurrence._enter_header(runtime, ctx, (TermValue(1),))
        ctx, _bound = recurrence._enter_target(
            runtime, ctx, (("v", TARGET_COORDINATE, TermValue(5)),)
        )
    assert recurrence._latched(runtime, ctx, 0) == (TermValue(5),)


def test_the_else_reads_the_last_items_target() -> None:
    recurrence = _recurrence()
    runtime = _target_runtime(carried=False)
    ctx = ReduceContext.root(owner="live-target-else")
    for index, value in enumerate((TermValue(5), TermValue(6))):
        with entered(_item(index)):
            ctx, _bound = recurrence._enter_target(
                runtime, ctx, (("v", TARGET_COORDINATE, value),)
            )
    after = recurrence._leave_target(runtime, ctx, 2)
    ref = EvaluationRefSugar(evaluation=TARGET, name="v", site=None)
    assert ref.desugar(after) == ExitSet.completed(TermValue(6))
    # No item: the target was never assigned, and nothing is bound.
    assert recurrence._leave_target(runtime, ctx, 0) is ctx


def test_the_publication_writes_the_loops_own_key_never_the_coordinate() -> None:
    # The loop publishes a name it carries under a binding coordinate under
    # its own key of the name: never the name, never the coordinate (another
    # loop writing the name carries it under the same one).
    recurrence = LoopRecurrenceSugar(
        target_cid=LOOP,
        loop_construction_cid="blake3-512:test-construction",
        binding_coordinate_cids=("blake3-512:test-binding",),
        post_binding_keys=(POST,),
        outward_faces=(),
        construction=None,
        site="live-loop-evaluation",
    )
    published = recurrence._publish_runtime_bindings(
        _RUNTIME,
        ReduceContext.root(owner="live-publication"),
        entries=(),
        carried=(TermValue(4),),
    )
    block = published.completed_value()
    assert block.statements == (ScopeRebind(POST, TermValue(4)),)


# -- a read inside a nested live loop's item ----------------------------------


def test_a_read_in_a_nested_item_reads_the_enclosing_items_write() -> None:
    # ``for row in rows: for c in cols: f(row)``: ``row`` is bound inside the
    # outer item and read inside an inner item.
    inner = loop_iteration_segment("blake3-512:inner-loop", 0)
    ctx = ReduceContext.root(owner="live-nested-read")
    with entered(_item(0)):
        ctx = ctx.with_temporal(
            ctx.temporal.bind_value(evaluation_here(KEY), TermValue(1))
        )
    with entered(_item(1)):
        ctx = ctx.with_temporal(
            ctx.temporal.bind_value(evaluation_here(KEY), TermValue(2))
        )
    ref = EvaluationRefSugar(evaluation=KEY, name="row", site=None)
    with entered(_item(1)):
        with entered(inner):
            assert ref.desugar(ctx) == ExitSet.completed(TermValue(2))
    # A write inside the inner item is that item's own.
    with entered(_item(1)):
        with entered(inner):
            ctx = ctx.with_temporal(
                ctx.temporal.bind_value(evaluation_here(KEY), TermValue(3))
            )
            assert ref.desugar(ctx) == ExitSet.completed(TermValue(3))
    with entered(_item(1)):
        assert ref.desugar(ctx) == ExitSet.completed(TermValue(2))


def test_a_read_in_an_item_reads_a_write_made_before_the_loop() -> None:
    ctx = ReduceContext.root(owner="live-outer-read")
    ctx = ctx.with_temporal(ctx.temporal.bind_value(KEY, TermValue(7)))
    ref = EvaluationRefSugar(evaluation=KEY, name="x", site=None)
    with entered(_item(0)):
        assert ref.desugar(ctx) == ExitSet.completed(TermValue(7))


# -- the latch: what an item hands on ----------------------------------------


def test_the_latch_is_the_items_last_evaluation() -> None:
    recurrence = _recurrence()
    ctx = ReduceContext.root(owner="live-latch")
    with entered(_item(0)):
        ctx = recurrence._enter_header(_RUNTIME, ctx, (TermValue(1),))
        # ``t += e`` binds its evaluation only (AugAssignSugar).
        ctx = ctx.with_temporal(
            ctx.temporal.bind_value(evaluation_here(LATCH), TermValue(3))
        )
    assert recurrence._latched(_RUNTIME, ctx, 0) == (TermValue(3),)


def test_an_item_that_rebinds_nothing_hands_on_its_header() -> None:
    recurrence = _recurrence()
    ctx = ReduceContext.root(owner="live-latch")
    ctx = ctx.with_temporal(ctx.temporal.bind_value("t", TermValue(1)))
    with entered(_item(0)):
        ctx = recurrence._enter_header(_RUNTIME, ctx, (TermValue(1),))
    assert recurrence._latched(_RUNTIME, ctx, 0) == (TermValue(1),)


_TWO_WRITES = SimpleNamespace(
    carried_names=("t",), carried_evaluations=((HEADER, (LATCH, WRITE), ()),)
)


def test_the_write_that_ran_last_is_handed_on() -> None:
    # ``t += e`` then ``t = e`` (an assignment binds its carried write), or
    # the assignment then a ``continue`` before the evaluation: whichever
    # write ran last on the path is what the item hands on.
    recurrence = _recurrence()
    ctx = ReduceContext.root(owner="live-latch")
    with entered(_item(0)):
        ctx = recurrence._enter_header(_TWO_WRITES, ctx, (TermValue(1),))
        ctx = ctx.with_temporal(
            ctx.temporal.bind_value(evaluation_here(LATCH), TermValue(3))
        )
        later = ctx.with_temporal(
            ctx.temporal.bind_value(evaluation_here(WRITE), TermValue(8))
        )
    assert recurrence._latched(_TWO_WRITES, later, 0) == (TermValue(8),)
    assert recurrence._latched(_TWO_WRITES, ctx, 0) == (TermValue(3),)


def test_a_write_of_the_name_is_not_read() -> None:
    # Only a write's key is read: the name holds no value the loop hands on.
    recurrence = _recurrence()
    ctx = ReduceContext.root(owner="live-latch")
    with entered(_item(0)):
        ctx = recurrence._enter_header(_RUNTIME, ctx, (TermValue(1),))
        ctx = ctx.with_temporal(
            ctx.temporal.bind_value(evaluation_here(LATCH), TermValue(3))
        )
        ctx = ctx.with_temporal(ctx.temporal.bind_value("t", TermValue(8)))
    assert recurrence._latched(_RUNTIME, ctx, 0) == (TermValue(3),)


def test_the_latch_reads_only_its_own_item() -> None:
    recurrence = _recurrence()
    ctx = ReduceContext.root(owner="live-latch")
    with entered(_item(0)):
        ctx = recurrence._enter_header(_RUNTIME, ctx, (TermValue(1),))
        ctx = ctx.with_temporal(
            ctx.temporal.bind_value(evaluation_here(LATCH), TermValue(3))
        )
    with entered(_item(1)):
        ctx = recurrence._enter_header(_RUNTIME, ctx, (TermValue(3),))
    # Item 1 has not evaluated ``t += e``: item 0's evaluation is not its own.
    assert recurrence._latched(_RUNTIME, ctx, 1) == (TermValue(3),)
    with entered(_item(1)):
        assert ctx.temporal.latest(evaluation_here(LATCH)) is None


# -- the else: after the last item -------------------------------------------

_ELSE = SimpleNamespace(
    carried_names=("t",), carried_evaluations=((HEADER, (LATCH,), (ELSE_WRITE,)),)
)


def test_the_else_reads_the_header_bound_after_the_last_item() -> None:
    recurrence = _recurrence()
    ctx = ReduceContext.root(owner="live-else")
    with entered(_item(0)):
        ctx = recurrence._enter_header(_ELSE, ctx, (TermValue(1),))
        ctx = ctx.with_temporal(
            ctx.temporal.bind_value(evaluation_here(LATCH), TermValue(4))
        )
    # Exhaustion: the header is bound outside every item, to the latch.
    ctx = recurrence._enter_header(_ELSE, ctx, recurrence._latched(_ELSE, ctx, 0))
    ref = EvaluationRefSugar(evaluation=HEADER, name="t", site=None)
    assert ref.desugar(ctx) == ExitSet.completed(TermValue(4))
    with entered(_item(0)):
        assert ref.desugar(ctx) == ExitSet.completed(TermValue(1))


def test_the_loop_leaves_with_the_elses_latest_write() -> None:
    recurrence = _recurrence()
    ctx = recurrence._enter_header(
        _ELSE, ReduceContext.root(owner="live-else"), (TermValue(4),)
    )
    # An else that writes nothing leaves with what the last item handed on.
    assert recurrence._after_else(_ELSE, ctx) == (TermValue(4),)
    # ``t += 10`` in the else binds its evaluation; the name is not read.
    ctx = ctx.with_temporal(ctx.temporal.bind_value(ELSE_WRITE, TermValue(14)))
    ctx = ctx.with_temporal(ctx.temporal.bind_value("t", TermValue(99)))
    assert recurrence._after_else(_ELSE, ctx) == (TermValue(14),)


def test_the_body_writes_are_not_the_elses() -> None:
    # A body write is keyed by its item; after the last item only the
    # else's writes and the header are read.
    recurrence = _recurrence()
    ctx = ReduceContext.root(owner="live-else")
    with entered(_item(0)):
        ctx = ctx.with_temporal(
            ctx.temporal.bind_value(evaluation_here(LATCH), TermValue(7))
        )
    ctx = recurrence._enter_header(_ELSE, ctx, (TermValue(4),))
    assert recurrence._after_else(_ELSE, ctx) == (TermValue(4),)


# -- construction ------------------------------------------------------------

_LIVE = (
    "def f(xs):\n"
    "    t = 0\n"
    "    for v in xs:\n"
    "        t += v\n"
    "    return t\n"
)


def _live_runtime(source: str = _LIVE):
    loop = next(
        statement
        for statement in _function(source).sugar().statements
        if type(statement).__name__ == "LoopRecurrenceSugar"
    )
    return loop.construction.loop_runtime


def test_a_live_body_reads_a_carried_name_through_the_header() -> None:
    runtime = _live_runtime()
    assert runtime.carried_names == ("t",)
    [(header, _writes, _else_writes)] = runtime.carried_evaluations
    assert header.startswith(EVALUATION_PREFIX)
    [aug] = runtime.body_sugars
    assert isinstance(aug, AugAssignSugar)
    # ``t += v`` reads ``t`` through the header, not by spelling.
    assert isinstance(aug.left, EvaluationRefSugar)
    assert aug.left.evaluation == header
    assert aug.left.name == "t"


def test_the_bodys_write_is_its_augmented_assignment() -> None:
    runtime = _live_runtime()
    [(header, writes, else_writes)] = runtime.carried_evaluations
    [aug] = runtime.body_sugars
    assert writes == (aug.evaluation,)
    assert aug.evaluation != header
    assert else_writes == ()


def test_an_assignment_in_the_body_is_a_keyed_write() -> None:
    # ``t = t + v`` binds its carried write of ``t``, never the name.
    runtime = _live_runtime(
        "def f(xs):\n"
        "    t = 0\n"
        "    for v in xs:\n"
        "        t = t + v\n"
        "    return t\n"
    )
    [(header, writes, _else_writes)] = runtime.carried_evaluations
    [assign] = runtime.body_sugars
    assert isinstance(assign, AssignSugar)
    assert writes == (carried_write_key(assign.site, "t"),)
    assert writes[0].startswith(EVALUATION_PREFIX)
    assert writes[0] != header


_LIVE_WHILE = (
    "def f(k):\n"
    "    n = k\n"
    "    while n:\n"
    "        n -= 1\n"
    "    return n\n"
)


def test_a_live_while_runs_its_items_through_the_header() -> None:
    # A live ``while`` has the for's runtime: its test and its body read the
    # carried name through the header, and its body's write is keyed.
    runtime = _live_runtime(_LIVE_WHILE)
    assert isinstance(runtime, LiveWhileRuntimeV1)
    assert runtime.carried_names == ("n",)
    [(header, writes, else_writes)] = runtime.carried_evaluations
    assert header.startswith(EVALUATION_PREFIX)
    assert isinstance(runtime.test_sugar, EvaluationRefSugar)
    assert runtime.test_sugar.evaluation == header
    [aug] = runtime.body_sugars
    assert isinstance(aug, AugAssignSugar)
    assert isinstance(aug.left, EvaluationRefSugar)
    assert aug.left.evaluation == header
    assert writes == (aug.evaluation,)
    assert else_writes == ()
    assert runtime.fuel > 0


# -- a name first bound in the loop is carried from unbound (#7757 item 7) -----


def _first_bound(items: str) -> str:
    # ``y`` is first bound in the loop: an item that takes the ``else`` arm
    # reads what an earlier item wrote, and ``z`` is read after the loop.
    return (
        "def f():\n"
        "    for x in g():\n"
        "        if x:\n"
        "            y = x\n"
        "        else:\n"
        "            z = y\n"
        "    return z\n"
        "def g():\n"
        f"    return {items}\n"
    )


def _returned_value(outcome):
    from sugar_lift_py_tests.floor.return_value import ReturnValue
    from sugar_lift_py_tests.floor.universe_value import UniverseValue

    universe = outcome.completed_value()
    assert isinstance(universe, UniverseValue), outcome
    (returned,) = [
        entry
        for entry in universe.record.statements
        if isinstance(entry, ReturnValue)
    ]
    return returned.value


def test_a_name_first_bound_in_the_loop_is_carried_from_unbound() -> None:
    runtime = _live_runtime(_first_bound("(1, 0)"))
    # ``y`` and ``z`` are carried through their headers, from unbound; no
    # binding entry stands for either, so each is published through its
    # post-loop key, as the target is through its own.
    assert runtime.carried_names == ("y", "z")
    assert runtime.initial_value_sugars == (None, None)
    assert runtime.coordinate_names == ()
    assert runtime.published_names == ("x", "y", "z")
    headers = {
        name: header
        for name, (header, _writes, _else_writes) in zip(
            runtime.carried_names, runtime.carried_evaluations, strict=True
        )
    }
    posts = dict(
        zip(runtime.published_names, runtime.published_evaluations, strict=True)
    )
    # The post-loop key of a carried name is its header's.
    assert posts["y"][0] == headers["y"]
    assert posts["z"][0] == headers["z"]


def test_a_later_item_reads_what_an_earlier_item_wrote() -> None:
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    # Item 0 writes ``y = 1``; item 1 reads it in ``z = y``; ``z`` is 1
    # after the loop.
    outcome = function_universe_outcome(_function(_first_bound("(1, 0)")))
    assert _returned_value(outcome) == TermValue(1)


def test_a_read_before_any_item_wrote_the_name_is_a_name_error() -> None:
    from sugar_lift_py_tests.effect import NameErrorEffect
    from sugar_lift_py_tests.outcome import Halted
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    # Item 0 takes the ``else`` arm: ``y`` was never written.
    outcome = function_universe_outcome(_function(_first_bound("(0, 1)")))
    halted = [exit_ for exit_ in outcome.exits if isinstance(exit_, Halted)]
    assert not [e for e in outcome.exits if isinstance(e, Completed)], outcome
    assert len(halted) == 1 and isinstance(halted[0].effect, NameErrorEffect)
    assert halted[0].effect.name == "y"


# -- a symbolic loop publishes what a concrete one does (#7757 item 7) ---------


def _returned_values(outcome) -> list:
    """Every value a completed exit of ``outcome`` returns, guarded or not."""
    from sugar_lift_py_tests.floor.guarded_return import GuardedReturn
    from sugar_lift_py_tests.floor.return_value import ReturnValue

    values = []
    for exit_ in outcome.exits:
        if not isinstance(exit_, Completed):
            continue
        record = getattr(exit_.value, "record", exit_.value)
        values.extend(
            entry.value
            for entry in getattr(record, "statements", ())
            if isinstance(entry, (ReturnValue, GuardedReturn))
        )
    return values


def _recurrence_value(function, name: str) -> SymbolicValue:
    """The symbolic loop's value of ``name``: its recurrence head under the
    key a read after the loop reads it through (its binding coordinate, or
    its post-loop key)."""
    loop = next(
        statement
        for statement in function.sugar().statements
        if isinstance(statement, LoopRecurrenceSugar)
    )
    runtime = loop.construction.loop_runtime
    if name in runtime.coordinate_names:
        key = loop.binding_coordinate_cids[runtime.coordinate_names.index(name)]
    else:
        key = runtime.published_evaluations[runtime.published_names.index(name)][0]
    return SymbolicValue(loop._recurrence_head(key))


def test_a_symbolic_loops_accumulator_reads_as_the_recurrences_value() -> None:
    from sugar_lift_py_tests.effect import NameErrorEffect
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    # ``xs`` is symbolic, so the loop runs as its recurrence.  It publishes
    # ``total`` as a concrete loop does: the read after the loop is the
    # recurrence's value of it, never refused for want of a binding.
    function = _function(
        "def f(xs):\n"
        "    total = 0\n"
        "    for x in xs:\n"
        "        total += x\n"
        "    return total\n"
    )
    outcome = function_universe_outcome(function)
    assert _recurrence_value(function, "total") in _returned_values(outcome)
    assert not [
        exit_
        for exit_ in outcome.exits
        if isinstance(exit_, Halted) and isinstance(exit_.effect, NameErrorEffect)
    ]


def test_a_name_first_bound_in_a_symbolic_loop_is_its_value_or_a_name_error() -> (
    None
):
    from sugar_lift_py_tests.effect import NameErrorEffect
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    # ``last`` is first bound in the loop: where some item wrote it the read
    # after the loop is the recurrence's value of it, where none did (``xs``
    # empty) it is a ``NameError``.  The loop's write slot of ``last`` is
    # authenticated as the guard that some item wrote it.
    function = _function(
        "def f(xs):\n"
        "    for x in xs:\n"
        "        last = x\n"
        "    return last\n"
    )
    outcome = function_universe_outcome(function)
    assert _recurrence_value(function, "last") in _returned_values(outcome)
    name_errors = [
        exit_
        for exit_ in outcome.exits
        if isinstance(exit_, Halted) and isinstance(exit_.effect, NameErrorEffect)
    ]
    assert [exit_.effect.name for exit_ in name_errors] == ["last"]


# -- a read after the loop is what the loop published, or refused (#7757) ------


def _flattened(values) -> list:
    """``values`` with every guarded value (a read over several exits)
    opened into the values of its arms."""
    from sugar_lift_py_tests.floor.guarded_value import GuardedValue

    flat = []
    pending = list(values)
    while pending:
        value = pending.pop()
        if isinstance(value, GuardedValue):
            pending.extend((value.when_true, value.when_false))
            continue
        flat.append(value)
    return flat


def test_a_break_under_a_symbolic_if_publishes_on_both_exits() -> None:
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    # ``g()`` is concrete, so the loop runs item by item; ``x == stop`` is
    # symbolic, so each item may leave by the ``break`` or go on.  ``carried``
    # is carried under its binding coordinate: the read after the loop is a
    # ``LoopBindingRef`` on each face (``BreakExit``, ``NormalExhaustion``),
    # and every exit the loop leaves by binds it -- the break in item 0 (the
    # pre-loop 0), the break in item 1 (1), and exhaustion (2).  None is
    # refused for want of a binding, and none is a made-up term.
    function = _function(
        "def f(stop):\n"
        "    carried = 0\n"
        "    for x in g():\n"
        "        if x == stop:\n"
        "            break\n"
        "        carried = x\n"
        "    return carried\n"
        "def g():\n"
        "    return (1, 2)\n"
    )
    outcome = function_universe_outcome(function)
    returned = _flattened(_returned_values(outcome))
    for value in (TermValue(0), TermValue(1), TermValue(2)):
        assert value in returned, (value, returned)


def test_an_unbound_loop_binding_ref_refuses_by_name() -> None:
    from sugar_lift_py_tests.gap.panic import ConstructionPanic

    ref = LoopBindingRefSugar(
        target_cid=LOOP,
        binding_coordinate_cid="blake3-512:test-binding",
        completion_kind="NormalExhaustion",
        name="carried",
        post_key=POST,
        site=None,
    )
    # No context, and a context the loop's publication never reached: the
    # read is refused naming the loop's key, the coordinate and the name,
    # never answered with an unbound ``python:loop.post_binding`` term.
    unpublished = ReduceContext.root(owner="live-unbound-post-binding")
    # A value under the coordinate is another loop's, or the binding before
    # the loop: never this loop's publication, so never read.
    elsewhere = unpublished.with_temporal(
        unpublished.temporal.bind_value("blake3-512:test-binding", TermValue(9))
    )
    for ctx in (None, unpublished, elsewhere):
        with pytest.raises(ConstructionPanic) as refused:
            ref.desugar(ctx)
        observed = refused.value.info.observed
        assert POST in observed
        assert "blake3-512:test-binding" in observed
        assert "`carried`" in observed
    # Bound by the loop's publication, the read is the published value.
    ctx = ReduceContext.root(owner="live-bound-post-binding")
    ctx = ctx.with_temporal(ctx.temporal.bind_value(POST, TermValue(4)))
    assert ref.desugar(ctx) == ExitSet.completed(TermValue(4))
    # Read inside the item of a live loop around it, the key published
    # outside that item is the one read.
    with entered(_item(0)):
        assert ref.desugar(ctx) == ExitSet.completed(TermValue(4))


# -- two loops writing one name: each publishes under its own key (#7757) -----


def _loops(function) -> list:
    return [
        statement
        for statement in function.sugar().statements
        if isinstance(statement, LoopRecurrenceSugar)
    ]


def test_two_loops_writing_one_name_publish_under_their_own_keys() -> None:
    # Both loops carry ``x`` under the binding coordinate the name has: the
    # second starts from the first's publication of it.  Each publishes it
    # under its own key, so no read after the one finds the other's value.
    function = _function(
        "def f(xs, ys):\n"
        "    x = 0\n"
        "    for a in xs:\n"
        "        x = a\n"
        "    for b in ys:\n"
        "        x = b\n"
        "    return x\n"
    )
    first, second = _loops(function)
    [first_key] = first.post_binding_keys
    [second_key] = second.post_binding_keys
    assert first_key.startswith(EVALUATION_PREFIX)
    assert second_key.startswith(EVALUATION_PREFIX)
    assert first_key != second_key


_HELPERS = "def g():\n    return (1, 2)\ndef h():\n    return (7, 8)\n"


def test_a_loop_in_an_if_after_a_loop_is_read_in_the_branch() -> None:
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    # The first loop leaves ``x`` 2; the second, inside the branch, leaves it
    # 8.  The read in the branch after the second loop is 8: never the first
    # loop's 2, which a key shared by both loops would hand it.
    function = _function(
        "def f(c):\n"
        "    x = 0\n"
        "    for a in g():\n"
        "        x = a\n"
        "    if c:\n"
        "        for b in h():\n"
        "            x = b\n"
        "        return x\n"
        "    return 5\n" + _HELPERS
    )
    returned = _flattened(_returned_values(function_universe_outcome(function)))
    assert TermValue(8) in returned, returned
    assert TermValue(5) in returned, returned
    assert TermValue(2) not in returned, returned


def test_a_loop_in_an_if_after_a_loop_is_read_after_the_if() -> None:
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    # After the ``if``: the second loop's 8 on the arm it ran, the first
    # loop's 2 on the arm it did not.  The ``if`` carries the second loop's
    # key out of its arm, so the read is not refused.
    function = _function(
        "def f(c):\n"
        "    x = 0\n"
        "    for a in g():\n"
        "        x = a\n"
        "    if c:\n"
        "        for b in h():\n"
        "            x = b\n"
        "    return x\n" + _HELPERS
    )
    returned = _flattened(_returned_values(function_universe_outcome(function)))
    assert TermValue(8) in returned, returned
    assert TermValue(2) in returned, returned
    assert TermValue(0) not in returned, returned


def test_a_loop_in_each_if_arm_is_read_after_the_if() -> None:
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    # Each arm's loop writes ``x``, carried under the one coordinate ``x = 0``
    # binds.  After the ``if``, each arm reads its own loop's key, carried
    # out of that arm: 2 on the one, 8 on the other, never the binding
    # before the ``if`` and never refused.
    function = _function(
        "def f(c):\n"
        "    x = 0\n"
        "    if c:\n"
        "        for a in g():\n"
        "            x = a\n"
        "    else:\n"
        "        for b in h():\n"
        "            x = b\n"
        "    return x\n" + _HELPERS
    )
    first, second = _loops_in_arms(function)
    assert first.post_binding_keys != second.post_binding_keys
    returned = _flattened(_returned_values(function_universe_outcome(function)))
    assert TermValue(2) in returned, returned
    assert TermValue(8) in returned, returned
    assert TermValue(0) not in returned, returned


def _loops_in_arms(function) -> list:
    """The live loops in the arms of ``function``'s ``if``, in source order."""
    from sugar_lift_py_tests.sugar.if_sugar import IfSugar

    [branch] = [
        statement
        for statement in function.sugar().statements
        if isinstance(statement, IfSugar)
    ]
    return [
        statement
        for statement in (*branch.then_body, *branch.else_body)
        if isinstance(statement, LoopRecurrenceSugar)
    ]


_LIVE_ELSE = (
    "def f(xs):\n"
    "    t = 0\n"
    "    for v in xs:\n"
    "        t += v\n"
    "    else:\n"
    "        t += 10\n"
    "    return t\n"
)


def test_the_else_reads_a_carried_name_through_the_header() -> None:
    runtime = _live_runtime(_LIVE_ELSE)
    assert runtime.carried_names == ("t",)
    [(header, writes, else_writes)] = runtime.carried_evaluations
    [body_aug] = runtime.body_sugars
    [else_aug] = runtime.else_sugars
    assert isinstance(else_aug, AugAssignSugar)
    # ``t += 10`` in the else reads ``t`` through the header, not by spelling.
    assert isinstance(else_aug.left, EvaluationRefSugar)
    assert else_aug.left.evaluation == header
    assert writes == (body_aug.evaluation,)
    assert else_writes == (else_aug.evaluation,)
    assert else_aug.evaluation != body_aug.evaluation


def test_the_same_source_gives_the_same_header() -> None:
    assert _live_runtime().carried_evaluations == _live_runtime().carried_evaluations


def test_a_live_body_reads_the_target_through_its_key() -> None:
    runtime = _live_runtime()
    [target] = runtime.target_evaluations
    assert target.startswith(EVALUATION_PREFIX)
    [aug] = runtime.body_sugars
    # ``t += v`` reads ``v`` through the item's projection, not by spelling.
    assert isinstance(aug.right, EvaluationRefSugar)
    assert aug.right.evaluation == target
    assert aug.right.name == "v"


def test_a_target_bound_before_the_loop_is_carried_through_its_key() -> None:
    runtime = _live_runtime(
        "def f(xs):\n"
        "    v = 0\n"
        "    for v in xs:\n"
        "        pass\n"
        "    return v\n"
    )
    assert runtime.carried_names == ("v",)
    [target] = runtime.target_evaluations
    assert runtime.carried_evaluations == ((target, (), ()),)


def test_a_nested_loop_rebinding_a_carried_target_is_a_write() -> None:
    # ``for x in xs: for x in ys``: the inner loop carries ``x`` and
    # publishes it; the outer latch reads that publication.
    runtime = _live_runtime(
        "def f(xs, ys):\n"
        "    x = 0\n"
        "    for x in xs:\n"
        "        for x in ys:\n"
        "            pass\n"
        "    return x\n"
    )
    assert runtime.carried_names == ("x",)
    [inner] = runtime.body_sugars
    assert isinstance(inner, LoopRecurrenceSugar)
    assert inner.construction.loop_runtime.carried_names == ("x",)
    [(_header, writes, _else_writes)] = runtime.carried_evaluations
    assert writes == inner.post_binding_keys


_SYMBOLIC_EXIT = (
    "def f(xs):\n"
    "    for x in xs:\n"
    "        if x:\n"
    "            return x\n"
)


def test_an_exit_in_the_symbolic_item_reads_the_items_target() -> None:
    # ``xs`` is symbolic, so the loop runs as its recurrence: ``return x`` is
    # an outward face reduced in the recurrence's one symbolic item, and its
    # read of ``x`` is the target's key, bound there to the item of ``xs``.
    loop = next(
        statement
        for statement in _function(_SYMBOLIC_EXIT).sugar().statements
        if isinstance(statement, LoopRecurrenceSugar)
    )
    assert loop.outward_faces
    xs = SymbolicValue(make_var("xs"))
    outcome = loop._desugar_with_iterable(
        xs, ReduceContext.root(owner="live-symbolic-item")
    )
    item = SymbolicValue(
        ctor(
            "python:loop.item",
            [str_const(loop.target_cid), xs.to_term(owner="test")],
            symbol_kind="coordinate",
        )
    )
    returned = [
        getattr(entry, "value", None)
        for exit_ in outcome.exits
        if isinstance(exit_, Completed)
        for entry in getattr(exit_.value, "statements", ())
    ]
    assert item in returned


def test_the_symbolic_item_binds_its_keys_in_its_own_segment() -> None:
    loop = next(
        statement
        for statement in _function(_SYMBOLIC_EXIT).sugar().statements
        if isinstance(statement, LoopRecurrenceSugar)
    )
    runtime = loop.construction.loop_runtime
    [target] = runtime.target_evaluations
    projected, enter, item = loop._enter_symbolic_item(
        runtime, ReduceContext.root(owner="live-symbolic-item"), None, ()
    )
    # A name target's unpack is the item whole: one plain arm.
    ctx = enter(projected.completed_value())
    ref = EvaluationRefSugar(evaluation=target, name="x", site=None)
    with item():
        assert live_iterations() == (loop_symbolic_item_segment(loop.target_cid),)
        bound = ref.desugar(ctx).completed_value()
    assert isinstance(bound, SymbolicValue)
    # Outside the item nothing is bound: the key is the item's own.
    assert ctx.temporal.value_if_bound(target) is None


_SYMBOLIC_UNPACK_EXIT = (
    "def f(xs):\n"
    "    for a, b in xs:\n"
    "        if a:\n"
    "            return b\n"
)


def test_an_exit_in_the_symbolic_item_reads_a_leaf_of_its_unpack() -> None:
    # ``xs`` is symbolic, so ``for a, b in xs`` runs as its recurrence: the
    # symbolic item unpacks through the same positional unpack a concrete
    # item does.  ``return b`` reads ``b``'s key, bound on the unpack's
    # completed arm to the item's second projection; the unpack's halt (too
    # few, too many, not iterable) is an arm of the recurrence, never dropped.
    loop = next(
        statement
        for statement in _function(_SYMBOLIC_UNPACK_EXIT).sugar().statements
        if isinstance(statement, LoopRecurrenceSugar)
    )
    assert loop.outward_faces
    xs = SymbolicValue(make_var("xs"))
    outcome = loop._desugar_with_iterable(
        xs, ReduceContext.root(owner="live-symbolic-unpack")
    )
    item = ctor(
        "python:loop.item",
        [str_const(loop.target_cid), xs.to_term(owner="test")],
        symbol_kind="coordinate",
    )
    second = SymbolicValue(
        ctor(
            "python:unpack.project",
            [item, num(1), num(2)],
            symbol_kind="coordinate",
        )
    )
    returned = [
        getattr(entry, "value", None)
        for exit_ in outcome.exits
        if isinstance(exit_, Completed)
        for entry in getattr(exit_.value, "statements", ())
    ]
    assert second in returned
    completes = atomic(
        "python:unpack.completes",
        [ctor("python:unpack.destructure", [item, num(2)], symbol_kind="coordinate")],
    )
    unpack_halts = [
        exit_
        for exit_ in outcome.exits
        if isinstance(exit_, Halted)
        and isinstance(exit_.effect, SequenceUnpackRuntimeEffect)
    ]
    assert [exit_.guard for exit_ in unpack_halts] == [not_(completes)]


_SYMBOLIC_UNPACK_NO_EXIT = (
    "def f(xs):\n"
    "    t = 0\n"
    "    for a, b in xs:\n"
    "        t += a\n"
    "    return t\n"
)


def test_a_symbolic_item_with_no_exit_still_unpacks_its_target() -> None:
    # The body has no ``return``/``raise``: the recurrence has no outward
    # face.  The symbolic item still unpacks its target, so the unpack's
    # halt is an arm of the loop and the recurrence follows its completed
    # arm -- the halt is never dropped for want of a face to reduce.
    loop = next(
        statement
        for statement in _function(_SYMBOLIC_UNPACK_NO_EXIT).sugar().statements
        if isinstance(statement, LoopRecurrenceSugar)
    )
    assert not loop.outward_faces
    xs = SymbolicValue(make_var("xs"))
    outcome = loop._desugar_with_iterable(
        xs, ReduceContext.root(owner="live-symbolic-unpack-no-exit")
    )
    item = ctor(
        "python:loop.item",
        [str_const(loop.target_cid), xs.to_term(owner="test")],
        symbol_kind="coordinate",
    )
    completes = atomic(
        "python:unpack.completes",
        [ctor("python:unpack.destructure", [item, num(2)], symbol_kind="coordinate")],
    )
    unpack_halts = [
        exit_
        for exit_ in outcome.exits
        if isinstance(exit_, Halted)
        and isinstance(exit_.effect, SequenceUnpackRuntimeEffect)
    ]
    assert [exit_.guard for exit_ in unpack_halts] == [not_(completes)]
    assert any(isinstance(exit_, Completed) for exit_ in outcome.exits)


_INNER_LOOP_EXIT = (
    "def f(xs):\n"
    "    for x in xs:\n"
    "        for y in g():\n"
    "            pass\n"
    "        return y\n"
    "def g():\n"
    "    return (1, 2)\n"
)


def test_an_exit_in_the_symbolic_item_reads_an_inner_loops_publication() -> None:
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    # ``xs`` is symbolic, so the outer loop runs as its recurrence and
    # ``return y`` is reduced in its one symbolic item.  The inner loop
    # ahead of it on its path runs there first, over ``g()``'s two items,
    # and publishes ``y`` through its post-loop key with its write slot
    # decided, so the exit's read decides: the last item, 2.  It is never
    # refused for want of an inner loop that did not run.
    function = _function(_INNER_LOOP_EXIT)
    loop = next(
        statement
        for statement in function.sugar().statements
        if isinstance(statement, LoopRecurrenceSugar)
    )
    (face,) = loop.outward_faces
    (inner,) = face.prefix_sugars
    assert isinstance(inner, LoopRecurrenceSugar)
    outcome = function_universe_outcome(function)
    assert TermValue(2) in _flattened(_returned_values(outcome))


_EXIT_AFTER_A_GUARDED_PREFIX = (
    "def f(xs):\n"
    "    for x in xs:\n"
    "        y = x\n"
    "        if x:\n"
    "            z = y\n"
    "            return z\n"
)


def test_an_exit_in_an_if_arm_runs_the_statements_ahead_of_the_if() -> None:
    # ``return z`` sits in an ``if`` arm: the statements ahead of it on its
    # path are ``y = x`` (ahead of the ``if``) and ``z = y`` (ahead of it in
    # the arm), in that order; the ``if`` itself is the face's guard.
    loop = next(
        statement
        for statement in _function(_EXIT_AFTER_A_GUARDED_PREFIX).sugar().statements
        if isinstance(statement, LoopRecurrenceSugar)
    )
    (face,) = loop.outward_faces
    assert len(face.prefix_sugars) == 2
    assert all(isinstance(sugar, AssignSugar) for sugar in face.prefix_sugars)
    xs = SymbolicValue(make_var("xs"))
    outcome = loop._desugar_with_iterable(
        xs, ReduceContext.root(owner="live-symbolic-prefix")
    )
    item = SymbolicValue(
        ctor(
            "python:loop.item",
            [str_const(loop.target_cid), xs.to_term(owner="test")],
            symbol_kind="coordinate",
        )
    )
    returned = [
        getattr(entry, "value", None)
        for exit_ in outcome.exits
        if isinstance(exit_, Completed)
        for entry in getattr(exit_.value, "statements", ())
    ]
    assert item in returned


def test_each_read_of_an_evaluation_is_spanned_at_its_use() -> None:
    rewritten = _function(
        "def f(x):\n    x += 1\n    y = x\n    return (x, y)\n"
    ).substitute({})
    aug, assign, ret = rewritten.body
    assert isinstance(aug, AugAssign)
    assert isinstance(assign, Assign)
    assert isinstance(ret, Return)
    assert isinstance(ret.value, Tuple_)
    read_x, read_y = ret.value.elts
    assert isinstance(read_x, EvaluationRef)
    assert isinstance(read_y, EvaluationRef)
    assert read_x.evaluation == aug.evaluation
    # ``y`` reads its own projection of ``y = x``'s evaluation, never the
    # reference ``y = x`` read; both reads are spanned at their own use.
    assert read_y.evaluation == projection_key(assign.evaluation, "y")
    assert read_y.name == "y"
    assert read_x.span != assign.value.span
    assert read_y.span != assign.value.span


# -- class bodies and the module block ----------------------------------------


def test_a_class_body_reads_the_evaluation() -> None:
    rewritten = _function(
        "def f():\n"
        "    x = 1\n"
        "    x += 1\n"
        "    class C:\n"
        "        y = x\n"
        "    return C\n"
    ).substitute({})
    aug = next(node for node in rewritten.body if isinstance(node, AugAssign))
    definition = next(node for node in rewritten.body if isinstance(node, ClassDef))
    field = definition.body[0]
    assert isinstance(field, Assign)
    assert isinstance(field.value, EvaluationRef)
    assert field.value.evaluation == aug.evaluation


def test_a_module_block_and_its_class_body_read_the_evaluation() -> None:
    # The module block threads its statements (``Module.substitute``); the
    # export prefix that threaded a module's prefix went in #7896.
    module = _source("x = 1\nx += 1\nclass C:\n    y = x\nz = x\n").root
    body = module.substitute({}).body
    aug = next(node for node in body if isinstance(node, AugAssign))
    definition = next(node for node in body if isinstance(node, ClassDef))
    field = definition.body[0]
    assert isinstance(field, Assign)
    assert isinstance(field.value, EvaluationRef)
    assert field.value.evaluation == aug.evaluation
    module_read = body[-1]
    assert isinstance(module_read, Assign)
    assert isinstance(module_read.value, EvaluationRef)
    assert module_read.value.evaluation == aug.evaluation
