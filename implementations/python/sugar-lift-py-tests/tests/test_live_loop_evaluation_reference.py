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
from sugar_lift_py_tests.effect import UndeterminedRaiseEffect
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
from sugar_lift_py_tests.sugar.builtin_container_call_sugar import (
    ContainerMutationStatementSugar,
)
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
    ClassDef,
    ContainerMutationStatement,
    EvaluationRef,
    FunctionDef,
    Return,
    Tuple_,
)
from sugar_source_tree.tree import SourceFile

KEY = EVALUATION_PREFIX + "blake3-512:test-evaluation"


def _is_in_place(node) -> bool:
    """A substituted ``x += e``: the one mutation door's statement writing
    its name to the in-place result under the statement's key (#7757)."""
    return isinstance(node, ContainerMutationStatement) and isinstance(
        getattr(node, "rebinds", None), str
    )


def _in_place_receiver(statement):
    """The read of the name a ``x += e`` statement's in-place call runs on."""
    assert isinstance(statement, ContainerMutationStatementSugar)
    return statement.evaluated[0].receiver


def _in_place_key(statement):
    """The key a ``x += e`` statement binds its in-place result under."""
    assert isinstance(statement, ContainerMutationStatementSugar)
    key, _index = statement.result_evaluation
    return key
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
        # ``t += e`` binds its evaluation only (the one mutation door's
        # statement binds its in-place result under it).
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
    left = _in_place_receiver(aug)
    # ``t += v`` reads ``t`` through the header, not by spelling.
    assert isinstance(left, EvaluationRefSugar)
    assert left.evaluation == header
    assert left.name == "t"


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
    left = _in_place_receiver(aug)
    assert isinstance(left, EvaluationRefSugar)
    assert left.evaluation == header
    assert writes == (_in_place_key(aug),)
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
    # authenticated as the guard that some item wrote it.  The loop leaves
    # by two records -- where the symbolic item ran, with what it left, and
    # where none ran -- so the read is reduced after each.
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
    assert name_errors
    assert {exit_.effect.name for exit_ in name_errors} == {"last"}


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


def test_a_loop_left_by_different_paths_in_an_if_is_read_after_the_if() -> None:
    from sugar_lift_py_tests.floor.guarded_value import GuardedValue
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    # The loop in the ``if`` leaves by the ``break`` in item 0 (``x`` 1), by
    # the ``break`` in item 1 (2), or by exhaustion (2): its key holds a
    # different value on each path.  The ``if`` carries each path's value
    # under that path's guard, so the read after the ``if`` is 1 or 2 on the
    # arm the loop ran and 5 on the other: never refused, never a value no
    # path left.  (``g()`` is concrete and runs item by item; a literal
    # iterable is unrolled before any loop key is minted.)
    function = _function(
        "def f(c, d):\n"
        "    x = 5\n"
        "    if c:\n"
        "        for x in g():\n"
        "            if x == d:\n"
        "                break\n"
        "    return x\n" + _HELPERS
    )
    values = _returned_values(function_universe_outcome(function))
    assert any(isinstance(value, GuardedValue) for value in values), values
    returned = _flattened(values)
    for value in (TermValue(1), TermValue(2), TermValue(5)):
        assert value in returned, (value, returned)
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
    else_left = _in_place_receiver(else_aug)
    # ``t += 10`` in the else reads ``t`` through the header, not by spelling.
    assert isinstance(else_left, EvaluationRefSugar)
    assert else_left.evaluation == header
    assert writes == (_in_place_key(body_aug),)
    assert else_writes == (_in_place_key(else_aug),)
    assert _in_place_key(else_aug) != _in_place_key(body_aug)


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
    ctx, _target_bindings = enter(projected.completed_value())
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
    unpack_halts = [exit_ for exit_ in outcome.exits if _is_unpack_halt(exit_)]
    assert [exit_.guard for exit_ in unpack_halts] == [not_(completes)]


def _is_unpack_halt(exit_) -> bool:
    """The runtime unpack's undetermined raise (``runtime_unpack_faces``)."""
    return (
        isinstance(exit_, Halted)
        and isinstance(exit_.effect, UndeterminedRaiseEffect)
        and str(exit_.effect.producer_node_owner).endswith(".unpack")
    )


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
    unpack_halts = [exit_ for exit_ in outcome.exits if _is_unpack_halt(exit_)]
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

    # ``xs`` is symbolic, so the outer loop runs as its recurrence and its
    # body runs once, in its one symbolic item.  The inner loop ahead of
    # ``return y`` runs there first, over ``g()``'s two items, and publishes
    # ``y`` through its post-loop key with its write slot decided, so the
    # exit's read decides: the last item, 2.  It is never refused for want
    # of an inner loop that did not run.
    function = _function(_INNER_LOOP_EXIT)
    loop = next(
        statement
        for statement in function.sugar().statements
        if isinstance(statement, LoopRecurrenceSugar)
    )
    (_face,) = loop.outward_faces
    # The item runs the whole body: the inner loop, then the return.
    body_sugars, _guard = loop._symbolic_item()
    assert len(body_sugars) == 2
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
    # ``return z`` sits in an ``if`` arm: the body runs once in the symbolic
    # item, ``y = x`` ahead of the ``if`` and ``z = y`` ahead of the return
    # in the arm, so the return reads ``z`` as the item; the ``if`` guards
    # the return's arm.
    loop = next(
        statement
        for statement in _function(_EXIT_AFTER_A_GUARDED_PREFIX).sugar().statements
        if isinstance(statement, LoopRecurrenceSugar)
    )
    (_face,) = loop.outward_faces
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


_TWO_EXITS_IN_ONE_ITEM = (
    "def f(xs):\n"
    "    for x in xs:\n"
    "        if x:\n"
    "            return 1\n"
    "        return 2\n"
)


def test_each_exit_of_the_symbolic_item_is_reported_once() -> None:
    # ``xs`` is symbolic: the body runs once in the symbolic item, so each
    # of its two exits is an arm of that one run -- ``return 1`` where ``x``
    # is truthy, ``return 2`` where it is not -- and each is reported
    # exactly once.  Replaying the statements ahead of ``return 2`` for it
    # alone reported ``return 1`` a second time.
    loop = next(
        statement
        for statement in _function(_TWO_EXITS_IN_ONE_ITEM).sugar().statements
        if isinstance(statement, LoopRecurrenceSugar)
    )
    assert len(loop.outward_faces) == 2
    outcome = loop._desugar_with_iterable(
        SymbolicValue(make_var("xs")), ReduceContext.root(owner="live-two-exits")
    )
    returned = _returned_values(outcome)
    assert len(returned) == 2, returned
    assert returned[0] != returned[1], returned


# -- what the symbolic item did leaves the loop with it (#7757 item 7) --------


_SYMBOLIC_APPEND = (
    "def f(xs):\n"
    "    acc = []\n"
    "    for x in xs:\n"
    "        acc.append(x)\n"
    "    return acc\n"
)


def _records(outcome) -> list:
    """The record of every completed exit of ``outcome``."""
    return [
        tuple(getattr(getattr(exit_.value, "record", exit_.value), "statements", ()))
        for exit_ in outcome.exits
        if isinstance(exit_, Completed)
    ]


def test_a_symbolic_items_append_leaves_the_loop_with_it() -> None:
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    # ``xs`` is symbolic and the body has no ``return``/``raise``: the
    # symbolic item still runs it, and what ``acc.append(x)`` left (the
    # receiver's post-state) leaves the loop on the arm where an item ran,
    # as a concrete item's entries do.  Where no item ran the loop leaves
    # without it: two records, never the item's append dropped into one.
    function = _function(_SYMBOLIC_APPEND)
    loop = next(
        statement
        for statement in function.sugar().statements
        if isinstance(statement, LoopRecurrenceSugar)
    )
    assert not loop.outward_faces
    records = _records(function_universe_outcome(function))
    assert len(records) >= 2, records
    shortest = min(len(record) for record in records)
    assert any(len(record) > shortest for record in records), records


def _recurrence_standing_as(stand: TermValue):
    """A stand-in for the loop leaving as its recurrence (``_left_with``):
    ``stand`` after what the item left; a halt leaves by itself, ``stand``
    after what its record holds."""
    from dataclasses import replace

    from sugar_lift_py_tests.floor.block_value import BlockValue

    def leave(entries=(), *, halt=None, can_fall_through=True):
        if halt is not None:
            return ExitSet.halted(
                halt.effect,
                state=replace(
                    halt.state, entries=(*entries, *halt.state.entries, stand)
                ),
            )
        return ExitSet.completed(
            BlockValue((*entries, stand), can_fall_through=can_fall_through)
        )

    return leave


def _left_by_the_item(body, *, exhausted=None):
    """The loop's exits from the symbolic item's ``body``, the recurrence
    standing as ``TermValue(0)`` after what the item left."""
    return LoopRecurrenceSugar._leave_symbolic_item(
        SimpleNamespace(target_cid=LOOP),
        body,
        _recurrence_standing_as(TermValue(0)),
        atomic("test.item", []),
        target_bindings=(),
        exhausted=exhausted,
    )


def _control_record(*entries):
    """A ``break``/``continue`` halt's record: what the item did before it
    (``entries``) and the context the statement received
    (``LoopControlSugar``)."""
    from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock

    return _ReducedBlock(
        entries,
        False,
        (),
        context=ReduceContext.root(owner="live-loop-control-record"),
    )


def _arm_of(left, value):
    """The one exit of ``left`` holding ``value``."""
    (arm,) = [exit_ for exit_ in left.exits if exit_.value == value]
    return arm


def test_the_symbolic_items_fall_through_leaves_with_its_entries() -> None:
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock

    # The item fell through having left an entry (a store, a mutation): the
    # loop goes on as its recurrence with it, under the item guard; where no
    # item ran, without it.
    left = _left_by_the_item(
        ExitSet.completed(_ReducedBlock((TermValue(1),), True, ()))
    )
    went_on = _arm_of(left, BlockValue((TermValue(1), TermValue(0))))
    assert "test.item" in str(went_on.guard)
    assert _arm_of(left, BlockValue((TermValue(0),))) is not None


def test_what_the_symbolic_item_owes_rides_onto_the_loops_result() -> None:
    from sugar_lift_py_tests.effect.loop_control_effect import LoopControlEffect
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock

    # An unanswered call in the body left a debt on the arm that fell
    # through, and on the arm that broke: the loop's arms continuing each
    # owe it, as every continuation of an arm does.
    test = atomic("test.x", [])
    body = ExitSet(
        (
            Halted(
                test,
                LoopControlEffect("break", LOOP, "blake3-512:test-break"),
                _control_record(),
                owed=("owed.before-break",),
            ),
            Completed(
                not_(test),
                _ReducedBlock((TermValue(1),), True, ()),
                owed=("owed.fell-through",),
            ),
        )
    )
    left = _left_by_the_item(body)
    went_on = _arm_of(left, BlockValue((TermValue(1), TermValue(0))))
    assert "owed.fell-through" in went_on.owed
    broke = _arm_of(left, BlockValue((TermValue(0),)))
    assert "owed.before-break" in broke.owed


def test_a_break_under_a_condition_keeps_its_partition_face() -> None:
    from sugar_lift_py_tests.effect.loop_control_effect import LoopControlEffect
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.outcome.exit_set import partition
    from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock

    # ``if x: break`` then a store: the item breaks on the ``if``'s then
    # face and falls through on its else face.  The arm that went on keeps
    # the else face and the guard it went on under; the arm that broke
    # leaves as the recurrence under the ``if``'s test.
    test = atomic("test.x", [])
    then_face, else_face = partition(("test.if", test))
    body = ExitSet(
        (
            Halted(
                test,
                LoopControlEffect("break", LOOP, "blake3-512:test-break"),
                _control_record(),
                frozenset({then_face}),
            ),
            Completed(
                not_(test),
                _ReducedBlock((TermValue(1),), True, ()),
                frozenset({else_face}),
            ),
        )
    )
    left = _left_by_the_item(body)
    went_on = _arm_of(left, BlockValue((TermValue(1), TermValue(0))))
    assert else_face in went_on.faces
    assert "test.x" in str(went_on.guard)
    broke = _arm_of(left, BlockValue((TermValue(0),)))
    assert "test.x" in str(broke.guard)


# -- an item's guarded return guards what follows it (#7757, found by #8126) --


def _subformulas(formula) -> list:
    """``formula`` and every formula a connective of it holds, at any depth."""
    found = []
    pending = [formula]
    while pending:
        current = pending.pop()
        found.append(current)
        if getattr(current, "kind", None) in ("and", "or", "not", "implies"):
            pending.extend(current.operands)
    return found


def _returns_by_arm(outcome) -> list:
    """``(guard, returns)`` of every completed exit of ``outcome``: its guard
    and every ``return`` its record holds, guarded or not."""
    from sugar_lift_py_tests.floor.guarded_return import GuardedReturn
    from sugar_lift_py_tests.floor.return_value import ReturnValue

    return [
        (
            exit_.guard,
            [
                entry
                for entry in getattr(
                    getattr(exit_.value, "record", exit_.value), "statements", ()
                )
                if isinstance(entry, (ReturnValue, GuardedReturn))
            ],
        )
        for exit_ in outcome.exits
        if isinstance(exit_, Completed)
    ]


_RETURN_FROM_AN_ITEM = (
    "def f({params}):\n"
    "    for x in {iterable}:\n"
    "        if x == c:\n"
    "            return x\n"
    "    return 0\n"
    "def g():\n"
    "    return (1, 2)\n"
)


def test_a_concrete_items_guarded_return_guards_every_later_item() -> None:
    from sugar_lift_py_tests.floor.guarded_return import GuardedReturn
    from sugar_lift_py_tests.floor.return_value import ReturnValue
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    # ``for x in (1, 2): if x == c: return x`` then ``return 0``: Python
    # takes one return.  Item 0 returns 1 under its ``x == c``; item 1 runs
    # only where item 0 did not return, and returns 2 under its own; ``0``
    # is returned only where neither did.  No arm holds a ``return`` beside
    # another: the item's guarded return never stands beside a later
    # unguarded ``return 0``.
    outcome = function_universe_outcome(
        _function(_RETURN_FROM_AN_ITEM.format(params="c", iterable="g()"))
    )
    arms = _returns_by_arm(outcome)
    assert arms, outcome
    for _guard, returns in arms:
        assert len(returns) == 1, arms

    def arm(value):
        (found,) = [
            (guard, entry) for guard, (entry,) in arms if entry.value == value
        ]
        return found

    first_guard, first = arm(TermValue(1))
    second_guard, second = arm(TermValue(2))
    zero_guard, zero = arm(TermValue(0))
    assert isinstance(first, GuardedReturn), first
    assert isinstance(second, GuardedReturn), second
    assert isinstance(zero, ReturnValue), zero
    # Item 1 runs only where item 0's return was not taken.
    for guard in first.guards:
        assert not_(guard) in _subformulas(second_guard), (guard, second_guard)
    # ``0`` only under the conjunction of every item's ``x != c``.
    for guard in (*first.guards, *second.guards):
        assert not_(guard) in _subformulas(zero_guard), (guard, zero_guard)
    assert first_guard != zero_guard


def test_a_symbolic_items_guarded_return_guards_the_loops_exit() -> None:
    from sugar_lift_py_tests.floor.guarded_return import GuardedReturn
    from sugar_lift_py_tests.floor.return_value import ReturnValue
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    # ``xs`` is symbolic: the symbolic item returns ``x`` under ``x == c``;
    # the loop goes on to ``return 0`` only where it did not (or where no
    # item ran), and no arm holds the item's return beside ``return 0``.
    outcome = function_universe_outcome(
        _function(_RETURN_FROM_AN_ITEM.format(params="c, xs", iterable="xs"))
    )
    arms = _returns_by_arm(outcome)
    assert arms, outcome
    for _guard, returns in arms:
        assert len(returns) == 1, arms
    items = [entry for _guard, (entry,) in arms if isinstance(entry, GuardedReturn)]
    assert items, arms
    zeros = [
        guard
        for guard, (entry,) in arms
        if isinstance(entry, ReturnValue) and entry.value == TermValue(0)
    ]
    assert zeros, arms
    for item in items:
        for guard in item.guards:
            assert any(not_(guard) in _subformulas(zero) for zero in zeros), (
                guard,
                zeros,
            )


def test_the_symbolic_items_guarded_return_is_not_carried_past_it() -> None:
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.floor.guarded_return import GuardedReturn
    from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock

    # The item stored, then took ``if c: return 1`` and fell through under
    # ``not c``: the loop leaves by that return under ``c`` with what the
    # item did, and goes on under ``not c`` with the store alone -- never
    # with the return the guard it goes on under excludes.
    test = atomic("test.c", [])
    returned = GuardedReturn((test,), TermValue(1))
    left = _left_by_the_item(
        ExitSet.completed(
            _ReducedBlock(
                (TermValue(2), returned),
                True,
                (not_(test),),
                context=ReduceContext.root(owner="live-guarded-return"),
            )
        )
    )
    took = _arm_of(
        left,
        BlockValue((TermValue(2), returned, TermValue(0)), can_fall_through=False),
    )
    assert test in _subformulas(took.guard)
    went_on = _arm_of(left, BlockValue((TermValue(2), TermValue(0))))
    assert not_(test) in _subformulas(went_on.guard)
    assert _arm_of(left, BlockValue((TermValue(0),))) is not None


def test_a_block_no_path_of_which_falls_through_ends_its_enclosing_block() -> None:
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.floor.guarded_return import GuardedReturn

    # A loop left by its item's guarded return (``can_fall_through`` false)
    # ends the enclosing block, as an unguarded return does: the statement
    # after the loop never runs on that arm.
    test = atomic("test.c", [])
    left = BlockValue(
        (GuardedReturn((test,), TermValue(1)),), can_fall_through=False
    )
    assert not left.follow_rest().continues
    assert BlockValue((GuardedReturn((test,), TermValue(1)),)).follow_rest().continues


# -- a break/continue leaves with what the item did (#7757 item 7, #8064) ------


def _holds(records, value) -> bool:
    """Whether some record (or a block nested in one) holds ``value``."""
    from sugar_lift_py_tests.floor.block_value import BlockValue

    pending = [entry for record in records for entry in record]
    while pending:
        entry = pending.pop()
        if entry == value:
            return True
        if isinstance(entry, BlockValue):
            pending.extend(entry.statements)
    return False


def _append_then(control: str, items: str) -> str:
    # ``acc.append(x)`` runs in the item ahead of its ``break``/``continue``.
    return (
        "def f():\n"
        "    acc = []\n"
        "    for x in g():\n"
        "        acc.append(x)\n"
        "        if x:\n"
        f"            {control}\n"
        "    return acc\n"
        "def g():\n"
        f"    return {items}\n"
    )


@pytest.mark.parametrize(
    ("control", "items"), [("break", "(1, 2)"), ("continue", "(1,)")]
)
def test_a_concrete_items_append_before_its_loop_control_leaves_with_it(
    control: str, items: str
) -> None:
    from sugar_lift_py_tests.floor.list_value import ListValue
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    # Item 0 appends 1 to ``acc`` and then breaks (or continues, and the
    # loop is exhausted): the receiver's post-state the append left is on
    # the record the loop leaves with, never dropped with the halt.
    outcome = function_universe_outcome(_function(_append_then(control, items)))
    records = _records(outcome)
    assert records, outcome
    assert _holds(records, ListValue((TermValue(1),))), records


def test_a_symbolic_items_append_before_its_break_leaves_with_it() -> None:
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    # ``xs`` is symbolic: the symbolic item appends and breaks.  The arm
    # where an item ran leaves with the append; the arm where none ran
    # leaves without it: two records, never one with the append dropped
    # (the breaking arm leaving as bare as the arm where no item ran).
    function = _function(
        "def f(xs):\n"
        "    acc = []\n"
        "    for x in xs:\n"
        "        acc.append(x)\n"
        "        break\n"
        "    return acc\n"
    )
    records = _records(function_universe_outcome(function))
    assert len(records) >= 2, records
    shortest = min(len(record) for record in records)
    assert any(len(record) > shortest for record in records), records


_STORE_THEN_BREAK = (
    "def f(xs):\n"
    "    for x in {iterable}:\n"
    "        y = x\n"
    "        break\n"
    "    return y\n"
    "def g():\n"
    "    return (1, 2)\n"
)


def test_a_concrete_items_store_before_its_break_is_read_after_the_loop() -> None:
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    # ``for x in (1, 2): y = x; break`` then ``return y``: item 0 stored 1
    # and broke, so ``y`` is 1.
    outcome = function_universe_outcome(
        _function(_STORE_THEN_BREAK.format(iterable="g()"))
    )
    assert _returned_value(outcome) == TermValue(1)


def test_a_symbolic_items_store_before_its_break_is_read_after_the_loop() -> None:
    from sugar_lift_py_tests.effect import NameErrorEffect
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    # ``xs`` is symbolic: where the item ran it stored ``y`` and broke, and
    # the read after the loop is the recurrence's value of ``y``; where no
    # item ran it is a ``NameError`` naming ``y``.  Nothing else.
    function = _function(_STORE_THEN_BREAK.format(iterable="xs"))
    outcome = function_universe_outcome(function)
    assert _recurrence_value(function, "y") in _flattened(_returned_values(outcome))
    name_errors = [
        exit_
        for exit_ in outcome.exits
        if isinstance(exit_, Halted) and isinstance(exit_.effect, NameErrorEffect)
    ]
    assert {exit_.effect.name for exit_ in name_errors} <= {"y"}


@pytest.mark.parametrize("action", ["break", "continue"])
def test_the_symbolic_items_loop_control_leaves_with_its_records_entries(
    action: str,
) -> None:
    from sugar_lift_py_tests.effect.loop_control_effect import LoopControlEffect
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock

    # ``x`` decides the item: it stored ``TermValue(1)`` and left by its
    # ``break``/``continue``, or stored ``TermValue(2)`` and fell through.
    # Each arm goes on as the recurrence after what its item did; where no
    # item ran, without either.
    test = atomic("test.x", [])
    body = ExitSet(
        (
            Halted(
                test,
                LoopControlEffect(action, LOOP, "blake3-512:test-control"),
                _control_record(TermValue(1)),
            ),
            Completed(not_(test), _ReducedBlock((TermValue(2),), True, ())),
        )
    )
    left = _left_by_the_item(body)
    controlled = _arm_of(left, BlockValue((TermValue(1), TermValue(0))))
    assert "test.x" in str(controlled.guard)
    assert "test.item" in str(controlled.guard)
    assert _arm_of(left, BlockValue((TermValue(2), TermValue(0)))) is not None
    assert _arm_of(left, BlockValue((TermValue(0),))) is not None


def test_a_loop_control_halt_without_its_record_is_refused() -> None:
    from sugar_lift_py_tests.effect.loop_control_effect import LoopControlEffect

    # A ``break`` whose halt carries no record (no context to authenticate,
    # no entries) is refused by name: the loop never leaves as if the item
    # did nothing.
    body = ExitSet.halted(LoopControlEffect("break", LOOP, "blake3-512:test-break"))
    with pytest.raises(TypeError, match="omitted its record"):
        _left_by_the_item(body)


@pytest.mark.parametrize("action", ["break", "continue"])
def test_a_concrete_items_loop_control_hands_on_its_records_entries(
    action: str,
) -> None:
    from sugar_lift_py_tests.effect.loop_control_effect import LoopControlEffect
    from sugar_lift_py_tests.floor.block_value import BlockValue

    # Item 0 left ``TermValue(1)`` before its ``break``/``continue``; the
    # items before it left ``TermValue(0)``.  ``continue`` takes both on to
    # the next item, from the record's context; ``break`` leaves the loop
    # with both.
    runtime = SimpleNamespace(carried_names=(), carried_evaluations=())
    record = _control_record(TermValue(1))
    (halt,) = ExitSet.halted(
        LoopControlEffect(action, LOOP, "blake3-512:test-control"), state=record
    ).exits
    resumed = []

    def resume(ctx, *, entries, carried, index):
        resumed.append((ctx, entries, carried, index))
        return ExitSet.completed(BlockValue(entries))

    outcome = _recurrence()._after_loop_control(
        halt, runtime, (), resume, entries=(TermValue(0),), index=0
    )
    assert outcome.completed_value() == BlockValue((TermValue(0), TermValue(1)))
    if action == "continue":
        assert resumed == [(record.context, (TermValue(0), TermValue(1)), (), 1)]
    else:
        assert resumed == []


def test_two_halts_whose_contexts_hold_an_evaluation_apart_stay_two_arms() -> None:
    from sugar_lift_py_tests.effect.loop_control_effect import LoopControlEffect
    from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock
    from sugar_lift_py_tests.temporal import bind_temporal

    # Two ``break`` arms with equal records whose contexts bind one
    # statement evaluation to different values are two paths: the loop
    # reads its latch from each one's context, so merged, one would be
    # read on both.
    root = ReduceContext.root(owner="live-loop-control-merge")

    def record(value):
        context = bind_temporal(root, KEY, value, owner="test", blame="test")
        return _ReducedBlock((), False, (), context=context)

    effect = LoopControlEffect("break", LOOP, "blake3-512:test-break")
    test = atomic("test.x", [])
    exits = ExitSet(
        (
            Halted(test, effect, record(TermValue(1))),
            Halted(not_(test), effect, record(TermValue(2))),
        )
    ).normalize()
    assert len(exits.exits) == 2, exits


# -- every halt leaving a loop carries what the items did (#7757 item 7) ------

OUTER = "blake3-512:test-outer-loop"


def _outer_break(state) -> Halted:
    """An enclosing loop's ``break`` from ``state``: a halt leaving this
    loop that is not its own control."""
    from sugar_lift_py_tests.effect.loop_control_effect import LoopControlEffect

    (halt,) = ExitSet.halted(
        LoopControlEffect("break", OUTER, "blake3-512:test-outer-break"),
        state=state,
    ).exits
    return halt


def _halt_records(outcome) -> list:
    """The record of every halted exit of ``outcome``."""
    return [
        tuple(getattr(exit_.state, "entries", ()))
        for exit_ in outcome.exits
        if isinstance(exit_, Halted)
    ]


def test_a_halt_leaving_a_concrete_item_carries_the_earlier_items_entries() -> None:
    # The items before it left ``TermValue(0)``; the item left
    # ``TermValue(1)`` before the halt.  The halt leaves the loop by itself,
    # its record holding both, from its own context.
    record = _control_record(TermValue(1))
    halt = _outer_break(record)
    outcome = _recurrence()._after_loop_control(
        halt,
        SimpleNamespace(carried_names=()),
        (),
        None,
        entries=(TermValue(0),),
        index=1,
    )
    (left,) = outcome.exits
    assert isinstance(left, Halted)
    assert left.effect == halt.effect
    assert left.state.entries == (TermValue(0), TermValue(1))
    assert left.state.context is record.context


def test_a_halt_with_nothing_to_carry_leaves_as_it_is() -> None:
    record = _control_record(TermValue(1))
    (left,) = _recurrence()._left_with((), (), halt=_outer_break(record)).exits
    assert left.state is record


@pytest.mark.parametrize("entries", [(), (TermValue(0),)])
def test_a_halt_without_a_record_is_refused_by_name(entries) -> None:
    from sugar_source_tree.panic import SugarNotWritten

    # Every halt carries a record built by its producer (``halt_record``):
    # a halt that offers none is refused by name, never given an empty
    # record in its place, whether or not there is anything to carry beside
    # it.
    with pytest.raises(SugarNotWritten) as refused:
        _recurrence()._left_with(entries, (), halt=_outer_break(None))
    assert refused.value.owner == "LoopRecurrenceSugar.left-with"


@pytest.mark.parametrize(
    "state", [ReduceContext.root(owner="live-loop-bare-halt"), "payload"]
)
def test_a_halt_whose_state_is_no_record_is_refused_by_name(state) -> None:
    from sugar_source_tree.panic import SugarNotWritten

    # A bare context or any other payload is no halt's state at all: the
    # halted arm is refused by name as it is built (#7757), so it never
    # reaches the loop to have the items' entries dropped beside it.
    with pytest.raises(SugarNotWritten) as refused:
        _outer_break(state)
    assert refused.value.owner == "Halted"


def test_a_halt_leaving_the_else_carries_the_loops_publication() -> None:
    # The ``else`` suite left ``TermValue(1)`` and halted; the items left
    # ``TermValue(0)``.  The halt leaves with both and the loop's
    # publication, bound in its context too, where an enclosing loop reads
    # its latch.
    recurrence = LoopRecurrenceSugar(
        target_cid=LOOP,
        loop_construction_cid="blake3-512:test-construction",
        binding_coordinate_cids=("blake3-512:test-binding",),
        post_binding_keys=(POST,),
        outward_faces=(),
        construction=None,
        site="live-loop-evaluation",
    )
    record = _control_record(TermValue(1))
    (left,) = recurrence._publish_runtime_bindings(
        _RUNTIME,
        record.context,
        entries=(TermValue(0),),
        carried=(TermValue(4),),
        items=1,
        else_ran=True,
        halt=_outer_break(record),
    ).exits
    assert isinstance(left, Halted)
    assert left.state.entries == (
        TermValue(0),
        TermValue(1),
        ScopeRebind(POST, TermValue(4)),
    )
    assert left.state.context.temporal.value_if_bound(POST) == TermValue(4)


def test_a_halt_leaving_an_else_that_writes_is_read_where_it_halted() -> None:
    from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock
    from sugar_lift_py_tests.sugar.loop_recurrence_sugar import (
        _else_left_from,
        _else_witnesses,
    )
    from sugar_lift_py_tests.temporal import bind_temporal
    from sugar_source_tree.panic import SugarNotWritten

    # The suite writes the carried name: the loop's publication is read
    # where the suite halted, a context holding the header the loop bound
    # for the suite.  A halt from another frame's context (a callee's
    # record) does not hold what the suite wrote: refused by name.
    runtime = SimpleNamespace(carried_evaluations=((HEADER, (), (ELSE_WRITE,)),))
    began = bind_temporal(
        ReduceContext.root(owner="live-else-began"),
        HEADER,
        TermValue(1),
        owner="test",
        blame="test",
    )
    witnesses = _else_witnesses(runtime, began)
    assert witnesses == ((HEADER, TermValue(1)),)
    halted_in = bind_temporal(
        began, ELSE_WRITE, TermValue(2), owner="test", blame="test"
    )
    halt = _outer_break(_ReducedBlock((), False, (), context=halted_in))
    assert _else_left_from(runtime, began, witnesses, halt, site=None) is halted_in
    callee = ReduceContext.root(owner="live-else-callee")
    foreign = _outer_break(_ReducedBlock((), False, (), context=callee))
    with pytest.raises(SugarNotWritten):
        _else_left_from(runtime, began, witnesses, foreign, site=None)
    # A suite that writes nothing leaves every name as it began.
    quiet = SimpleNamespace(carried_evaluations=((HEADER, (), ()),))
    assert _else_left_from(quiet, began, witnesses, foreign, site=None) is began


def test_a_halt_leaving_the_symbolic_item_carries_what_the_items_did() -> None:
    from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock

    # ``x`` decides the item: it left ``TermValue(1)`` and an enclosing
    # loop's ``break`` left it, or it left ``TermValue(2)`` and fell
    # through.  The halt leaves by itself with what the item did and the
    # recurrence (what the items before it did), under the item's guard.
    test = atomic("test.x", [])
    record = _control_record(TermValue(1))
    body = ExitSet(
        (
            Halted(test, _outer_break(record).effect, record),
            Completed(not_(test), _ReducedBlock((TermValue(2),), True, ())),
        )
    )
    (left,) = [
        exit_ for exit_ in _left_by_the_item(body).exits if isinstance(exit_, Halted)
    ]
    assert left.state.entries == (TermValue(1), TermValue(0))
    assert "test.x" in str(left.guard)
    assert "test.item" in str(left.guard)


@pytest.mark.parametrize(("action", "stand"), [("break", 0), ("continue", 9)])
def test_the_symbolic_items_continue_is_exhausted_and_its_break_is_not(
    action: str, stand: int
) -> None:
    from sugar_lift_py_tests.effect.loop_control_effect import LoopControlEffect
    from sugar_lift_py_tests.floor.block_value import BlockValue

    # Exhausted (``TermValue(9)``: through the ``else`` suite), the loop
    # leaves after a ``continue`` and where no item ran; after a ``break``
    # it leaves as the recurrence (``TermValue(0)``), the ``else`` not run.
    body = ExitSet.halted(
        LoopControlEffect(action, LOOP, "blake3-512:test-control"),
        state=_control_record(TermValue(1)),
    )
    left = _left_by_the_item(body, exhausted=_recurrence_standing_as(TermValue(9)))
    values = [exit_.value for exit_ in left.exits]
    assert BlockValue((TermValue(1), TermValue(stand))) in values
    assert BlockValue((TermValue(9),)) in values


_RAISE_IN_AN_ITEM = (
    "def f(xs):\n"
    "    acc = []\n"
    "    for x in {iterable}:\n"
    "        acc.append(x)\n"
    "        if x == 2:\n"
    "            raise ValueError()\n"
    "    return acc\n"
    "def g():\n"
    "    return (1, 2)\n"
)


def test_a_raise_leaving_a_concrete_item_carries_the_earlier_items_appends() -> None:
    from sugar_lift_py_tests.floor.list_value import ListValue
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    # Item 0 appended 1 and went on; item 1 appended 2 and raised.  The
    # raise leaves the loop with item 0's append as well as its own.
    outcome = function_universe_outcome(
        _function(_RAISE_IN_AN_ITEM.format(iterable="g()"))
    )
    records = _halt_records(outcome)
    assert records, outcome
    assert _holds(records, ListValue((TermValue(1),))), records
    assert _holds(records, ListValue((TermValue(1), TermValue(2)))), records


def _recurrence_facts(records, head) -> list:
    """Every recurrence fact (``head = python:loop.step(head, ...)``) the
    records hold for ``head``."""
    from sugar_lift_py_tests.floor import InvValue

    facts = []
    for record in records:
        for entry in record:
            if not isinstance(entry, InvValue):
                continue
            if tuple(getattr(entry.formula, "args", ()))[:1] == (head,):
                facts.append(entry)
    return facts


def _publishes(records, value) -> bool:
    """Whether some record holds a publication (``ScopeRebind``) of
    ``value``."""
    for record in records:
        for entry in record:
            if isinstance(entry, ScopeRebind) and entry.value == value:
                return True
    return False


def test_a_raise_leaving_the_symbolic_item_carries_the_recurrence() -> None:
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    # ``xs`` is symbolic: where the item raises, it leaves the loop with what
    # it did and the recurrence, which is what the items before it did.
    function = _function(_RAISE_IN_AN_ITEM.format(iterable="xs"))
    outcome = function_universe_outcome(function)
    head = _recurrence_value(function, "x").term
    assert _recurrence_facts(_halt_records(outcome), head), outcome


_RAISE_IN_THE_ELSE = (
    "def f(xs):\n"
    "    acc = []\n"
    "    for x in {iterable}:\n"
    "        acc.append(x)\n"
    "    else:\n"
    "        raise ValueError()\n"
    "    return acc\n"
    "def g():\n"
    "    return (1, 2)\n"
)


def test_a_raise_leaving_a_concrete_else_carries_the_items_and_publication() -> None:
    from sugar_lift_py_tests.floor.list_value import ListValue
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    # Both items appended, then the ``else`` raised: the raise leaves with
    # both appends and the loop's publication of the target's last value.
    outcome = function_universe_outcome(
        _function(_RAISE_IN_THE_ELSE.format(iterable="g()"))
    )
    records = _halt_records(outcome)
    assert _holds(records, ListValue((TermValue(1),))), records
    assert _holds(records, ListValue((TermValue(1), TermValue(2)))), records
    assert _publishes(records, TermValue(2)), records


def test_a_raise_leaving_a_symbolic_loops_else_carries_the_publication() -> None:
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    # ``xs`` is symbolic: the loop is exhausted where an item ran and where
    # none did, and its ``else`` runs there and raises.  The raise leaves
    # with the recurrence and the loop's publication of the target.
    function = _function(_RAISE_IN_THE_ELSE.format(iterable="xs"))
    outcome = function_universe_outcome(function)
    records = _halt_records(outcome)
    head = _recurrence_value(function, "x")
    assert _recurrence_facts(records, head.term), outcome
    assert _publishes(records, head), records


_BREAK_IN_THE_ELSE = (
    "def f(xs):\n"
    "    acc = []\n"
    "    for y in g():\n"
    "        for x in {iterable}:\n"
    "            acc.append(x)\n"
    "        else:\n"
    "            break\n"
    "        return 0\n"
    "    return acc\n"
    "def g():\n"
    "    return (1, 2)\n"
)


def test_an_outer_break_in_a_concrete_loops_else_carries_the_items() -> None:
    from sugar_lift_py_tests.floor.list_value import ListValue
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    # The inner loop appended 1 and 2, then its ``else`` broke the outer
    # loop: the outer loop leaves with the inner items' appends.
    outcome = function_universe_outcome(
        _function(_BREAK_IN_THE_ELSE.format(iterable="g()"))
    )
    records = _records(outcome)
    assert records, outcome
    assert _holds(records, ListValue((TermValue(1),))), records
    assert _holds(records, ListValue((TermValue(1), TermValue(2)))), records
    assert TermValue(0) not in _flattened(_returned_values(outcome))


def test_an_outer_break_in_a_symbolic_loops_else_leaves_the_outer_loop() -> None:
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    # ``xs`` is symbolic: the inner loop is exhausted where an item ran and
    # where none did, and its ``else`` breaks the outer loop there, so the
    # outer item never reaches ``return 0``.
    outcome = function_universe_outcome(
        _function(_BREAK_IN_THE_ELSE.format(iterable="xs"))
    )
    returned = _flattened(_returned_values(outcome))
    assert returned, outcome
    assert TermValue(0) not in returned, returned


def test_each_read_of_an_evaluation_is_spanned_at_its_use() -> None:
    rewritten = _function(
        "def f(x):\n    x += 1\n    y = x\n    return (x, y)\n"
    ).substitute({})
    aug, assign, ret = rewritten.body
    assert _is_in_place(aug)
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
    aug = next(node for node in rewritten.body if _is_in_place(node))
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
    aug = next(node for node in body if _is_in_place(node))
    definition = next(node for node in body if isinstance(node, ClassDef))
    field = definition.body[0]
    assert isinstance(field, Assign)
    assert isinstance(field.value, EvaluationRef)
    assert field.value.evaluation == aug.evaluation
    module_read = body[-1]
    assert isinstance(module_read, Assign)
    assert isinstance(module_read.value, EvaluationRef)
    assert module_read.value.evaluation == aug.evaluation
