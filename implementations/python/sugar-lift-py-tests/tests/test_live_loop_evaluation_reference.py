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
  body's last ``x += e`` evaluation, the header and a write of the name.

A class body and a module block are threaded by substitution, so their reads
after ``x += e`` are references too.  (The export prefix, the third reader
#7886 named, went in #7896.)
"""

from __future__ import annotations

from types import SimpleNamespace

from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.occurrence import (
    entered,
    live_iterations,
    loop_iteration_segment,
    occurrence_path,
)
from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.augassign_sugar import AugAssignSugar
from sugar_lift_py_tests.sugar.evaluation_ref_sugar import (
    EvaluationRefSugar,
    evaluation_here,
)
from sugar_lift_py_tests.sugar.loop_recurrence_sugar import LoopRecurrenceSugar
from sugar_lift_py_tests.temporal.temporal_context import EVALUATION_PREFIX
from sugar_lift_python_source.canonical import blake3_512_of
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
        outward_faces=(),
        construction=None,
        site="live-loop-evaluation",
    )


_RUNTIME = SimpleNamespace(
    carried_names=("t",), carried_evaluations=((HEADER, LATCH),)
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


def test_a_loop_target_has_no_header() -> None:
    recurrence = _recurrence()
    runtime = SimpleNamespace(
        carried_names=("v",), carried_evaluations=((None, None),)
    )
    ctx = ReduceContext.root(owner="live-header")
    with entered(_item(0)):
        entered_ctx = recurrence._enter_header(runtime, ctx, (TermValue(1),))
    assert entered_ctx.temporal.evaluations() == ()


# -- the latch: what an item hands on ----------------------------------------


def test_the_latch_is_the_items_last_evaluation() -> None:
    recurrence = _recurrence()
    ctx = ReduceContext.root(owner="live-latch")
    with entered(_item(0)):
        ctx = recurrence._enter_header(_RUNTIME, ctx, (TermValue(1),))
        # ``t += e``: the name first, the evaluation last (AugAssignSugar).
        ctx = ctx.with_temporal(ctx.temporal.bind_value("t", TermValue(3)))
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


def test_a_later_write_of_the_name_is_handed_on() -> None:
    # A binder that is no statement evaluation (an assignment, a nested
    # loop's publication) writes the name after the evaluation.
    recurrence = _recurrence()
    ctx = ReduceContext.root(owner="live-latch")
    with entered(_item(0)):
        ctx = recurrence._enter_header(_RUNTIME, ctx, (TermValue(1),))
        ctx = ctx.with_temporal(
            ctx.temporal.bind_value(evaluation_here(LATCH), TermValue(3))
        )
        ctx = ctx.with_temporal(ctx.temporal.bind_value("t", TermValue(8)))
    assert recurrence._latched(_RUNTIME, ctx, 0) == (TermValue(8),)


def test_the_latch_reads_only_its_own_item() -> None:
    recurrence = _recurrence()
    ctx = ReduceContext.root(owner="live-latch")
    with entered(_item(0)):
        ctx = recurrence._enter_header(_RUNTIME, ctx, (TermValue(1),))
        ctx = ctx.with_temporal(ctx.temporal.bind_value("t", TermValue(3)))
        ctx = ctx.with_temporal(
            ctx.temporal.bind_value(evaluation_here(LATCH), TermValue(3))
        )
    with entered(_item(1)):
        ctx = recurrence._enter_header(_RUNTIME, ctx, (TermValue(3),))
    # Item 1 has not evaluated ``t += e``: item 0's evaluation is not its own.
    assert recurrence._latched(_RUNTIME, ctx, 1) == (TermValue(3),)
    with entered(_item(1)):
        assert ctx.temporal.latest(evaluation_here(LATCH)) is None


# -- construction ------------------------------------------------------------

_LIVE = (
    "def f(xs):\n"
    "    t = 0\n"
    "    for v in xs:\n"
    "        t += v\n"
    "    return t\n"
)


def _live_runtime():
    loop = next(
        statement
        for statement in _function(_LIVE).sugar().statements
        if type(statement).__name__ == "LoopRecurrenceSugar"
    )
    return loop.construction.loop_runtime


def test_a_live_body_reads_a_carried_name_through_the_header() -> None:
    runtime = _live_runtime()
    assert runtime.carried_names == ("t",)
    [(header, _latch)] = runtime.carried_evaluations
    assert header.startswith(EVALUATION_PREFIX)
    [aug] = runtime.body_sugars
    assert isinstance(aug, AugAssignSugar)
    # ``t += v`` reads ``t`` through the header, not by spelling.
    assert isinstance(aug.left, EvaluationRefSugar)
    assert aug.left.evaluation == header
    assert aug.left.name == "t"


def test_the_latch_is_the_bodys_last_augmented_assignment() -> None:
    runtime = _live_runtime()
    [(header, latch)] = runtime.carried_evaluations
    [aug] = runtime.body_sugars
    assert latch == aug.evaluation
    assert latch != header


def test_the_same_source_gives_the_same_header() -> None:
    assert _live_runtime().carried_evaluations == _live_runtime().carried_evaluations


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
    assert read_x.evaluation == read_y.evaluation == aug.evaluation
    # ``x`` is read at its own use; ``y`` reads what ``y = x`` read.
    assert read_x.span != assign.value.span
    assert read_y.span == assign.value.span


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
