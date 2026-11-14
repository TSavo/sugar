"""Where a walrus's write goes when its key was never bound (#7757 item 7,
after #7938).

#7938 made a read after ``(x := e)`` resolve through the walrus's key only,
refused by name where the key was never bound.  These are the places that
still had no bind:

1. A walrus in a live loop's body, read after the loop: the loop carries the
   name, latched from the item's walrus write as ``x += e``'s is, and the read
   after the loop is the loop's carried value.
2. A walrus in a comprehension over a symbolic iterable: its write is the
   last member's, guarded by some member writing; on the other arm the name
   keeps its prior binding.
3. A walrus in a comprehension's condition writes per member, kept or not.
   A generator expression's walrus writes when the generator is consumed:
   the read after it is undecided by name, and a live loop it would feed is
   refused.  (A walrus in a comprehension's iterable does not compile:
   PEP 572.)
4. An empty finite comprehension writes nothing: the read after it takes the
   prior binding.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.floor.block_value import BlockValue
from sugar_lift_py_tests.floor.comprehension_value import ComprehensionValue
from sugar_lift_py_tests.floor.guarded_value import GuardedValue
from sugar_lift_py_tests.floor.named_expression_value import (
    NamedExpressionValue,
    bind_walrus_binds,
    peel_walrus_binds,
)
from sugar_lift_py_tests.floor.return_value import ReturnValue
from sugar_lift_py_tests.occurrence import entered, loop_iteration_segment
from sugar_lift_py_tests.outcome import Completed, ExitSet
from sugar_lift_py_tests.sugar.evaluation_ref_sugar import EvaluationRefSugar
from sugar_lift_py_tests.sugar.loop_recurrence_sugar import LoopRecurrenceSugar
from sugar_lift_py_tests.temporal.temporal_context import EVALUATION_PREFIX
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Call, EvaluationRef, FunctionDef, Return
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile

HEADER = EVALUATION_PREFIX + "blake3-512:test-walrus-header"
WALRUS = EVALUATION_PREFIX + "blake3-512:test-walrus-latch"
LOOP = "blake3-512:test-walrus-loop"


def _source(source: str, name: str = "walrus_writes.py") -> SourceFile:
    return SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _function(source: str) -> FunctionDef:
    return next(
        node for node in _source(source).nodes() if isinstance(node, FunctionDef)
    )


def _walruses(node) -> list:
    return [child for child in node.walk() if child.kind == "NamedExpr"]


def _comprehension(node, kind: str):
    return next(child for child in node.walk() if child.kind == kind)


def _root(owner: str = "walrus-writes") -> ReduceContext:
    return ReduceContext.root(owner=owner)


def _value(outcome):
    return outcome.completed_value()


def _returned_value(outcome):
    """The one completed return value of a reduced call."""
    assert isinstance(outcome, ExitSet), type(outcome)
    assert len(outcome.exits) == 1
    face = outcome.exits[0]
    assert isinstance(face, Completed), type(face)
    value = face.value
    force = getattr(value, "force_floor", None)
    if callable(force):
        forced = force(None, owner="walrus_writes_test")
        if isinstance(forced, BlockValue):
            returns = [s for s in forced.statements if isinstance(s, ReturnValue)]
            assert returns, forced.statements
            return returns[-1].value
        return forced
    record = getattr(value, "record", None)
    if record is not None:
        returns = [s for s in record.statements if isinstance(s, ReturnValue)]
        if returns:
            return returns[-1].value
    return value


def _call_outcome(source: str):
    """``source``'s last call, reduced through the production door."""
    tree = _source(source, "walrus_writes_call.py")
    call = tuple(node for node in tree.nodes() if isinstance(node, Call))[-1]
    return call.sugar().desugar(None)


# ---------------------------------------------------------------------------
# 1. A walrus in a live loop's body: the loop carries the name
# ---------------------------------------------------------------------------

_LIVE = "def f(xs):\n    t = 0\n    for v in xs:\n        (t := v)\n    return t\n"


def test_a_read_after_a_live_loop_reads_the_loops_carried_value() -> None:
    rewritten = _function(_LIVE).substitute({})
    ret = rewritten.body[-1]
    assert isinstance(ret, Return)
    # Not a reference to the walrus's construct-time key, which no item
    # binds (each item's write is under its own qualified key): the loop's
    # projected post-binding of `t`.
    assert not isinstance(ret.value, EvaluationRef)
    assert ret.value.kind == "GuardedBindingRead"


def test_a_live_loop_latches_its_walrus() -> None:
    (walrus,) = _walruses(_function(_LIVE).substitute({}))
    loop = next(
        statement
        for statement in _function(_LIVE).sugar().statements
        if type(statement).__name__ == "LoopRecurrenceSugar"
    )
    runtime = loop.construction.loop_runtime
    assert runtime.carried_names == ("t",)
    [(header, writes, else_writes)] = runtime.carried_evaluations
    # The item hands on its walrus's write, as it hands on `t += v`'s.
    assert writes == (walrus.evaluation,)
    assert walrus.evaluation != header
    assert else_writes == ()


def test_the_latch_is_the_items_walrus_write() -> None:
    recurrence = LoopRecurrenceSugar(
        target_cid=LOOP,
        loop_construction_cid="blake3-512:test-walrus-construction",
        binding_coordinate_cids=(),
        outward_faces=(),
        construction=None,
        site="walrus-latch",
    )
    runtime = SimpleNamespace(
        carried_names=("t",), carried_evaluations=((HEADER, (WALRUS,), ()),)
    )
    ctx = _root("walrus-latch")
    with entered(loop_iteration_segment(LOOP, 0)):
        ctx = recurrence._enter_header(runtime, ctx, (TermValue(1),))
        ctx = NamedExpressionValue("t", TermValue(7), evaluation=WALRUS).bind(ctx)
    assert recurrence._latched(runtime, ctx, 0) == (TermValue(7),)


def test_a_generator_walrus_writing_a_carried_name_is_refused() -> None:
    # The generator writes `n` when `sum` consumes it, and that write is not
    # carried out of `sum`: the next item's `n` would be the header's.
    with pytest.raises(SugarNotWritten):
        _function(
            "def f(xss):\n"
            "    n = 0\n"
            "    for xs in xss:\n"
            "        s = sum((n := x) for x in xs)\n"
            "    return n\n"
        ).substitute({})


# ---------------------------------------------------------------------------
# 2. A symbolic iterable: the last member's write, guarded by a write
# ---------------------------------------------------------------------------


def test_a_symbolic_comprehension_carries_the_last_write_or_the_prior() -> None:
    rewritten = _function(
        "def f(xs):\n    n = 0\n    ys = [(n := x) for x in xs]\n    return n\n"
    ).substitute({})
    (walrus,) = _walruses(rewritten)
    comprehension = _comprehension(rewritten, "ListComp")
    carried = _value(comprehension.sugar().desugar(_root("walrus-symbolic")))
    binds, presented = peel_walrus_binds(carried)
    assert isinstance(presented, ComprehensionValue)
    assert presented.finite_elements is None
    assert [(bind.name, bind.evaluation) for bind in binds] == [
        ("n", walrus.evaluation)
    ]
    written = binds[0].assigned_value
    # Some member wrote: the last write.  None did: `n` is still 0.
    assert isinstance(written, GuardedValue)
    assert written.when_false == TermValue(0)
    assert (
        written.when_true.to_term(owner="walrus-symbolic").name
        == "python:comprehension.last_write"
    )
    after = bind_walrus_binds(binds, _root("walrus-after-symbolic"))
    ret = rewritten.body[-1]
    assert isinstance(ret, Return)
    assert _value(ret.value.sugar().desugar(after)) == written


# ---------------------------------------------------------------------------
# 3. A condition writes per member; a generator writes when consumed
# ---------------------------------------------------------------------------


def test_a_condition_walrus_writes_for_every_member_it_reaches() -> None:
    rewritten = _function(
        "def f():\n    [v for v in [1, 2, 3] if (seen := v) > 1]\n    return seen\n"
    ).substitute({})
    (walrus,) = _walruses(rewritten)
    comprehension = _comprehension(rewritten, "ListComp")
    carried = _value(comprehension.sugar().desugar(_root("walrus-condition")))
    binds, presented = peel_walrus_binds(carried)
    # The condition ran for every member, kept or not: the last write is 3.
    assert [(bind.name, bind.evaluation, bind.assigned_value) for bind in binds] == [
        ("seen", walrus.evaluation, TermValue(3))
    ]
    # The fold kept the members the presented verdict kept.
    assert presented.finite_elements == (TermValue(2), TermValue(3))


def test_a_read_after_a_condition_walrus_is_its_last_write() -> None:
    returned = _returned_value(
        _call_outcome(
            "def f():\n"
            "    [v for v in [1, 2, 3] if (seen := v) > 1]\n"
            "    return seen\n"
            "\n"
            "f()\n"
        )
    )
    assert returned == TermValue(3)


def test_a_generator_walrus_read_is_undecided_by_name() -> None:
    rewritten = _function(
        "def f():\n    g = ((n := v) for v in [1, 2])\n    return n\n"
    ).substitute({})
    generator = _comprehension(rewritten, "GeneratorExp")
    # Making the generator writes nothing.
    carried = _value(generator.sugar().desugar(_root("walrus-generator")))
    binds, _presented = peel_walrus_binds(carried)
    assert binds == ()
    ret = rewritten.body[-1]
    assert isinstance(ret, Return)
    assert isinstance(ret.value, EvaluationRef)
    assert getattr(ret.value, "deferred", False) is True
    read = ret.value.sugar()
    assert isinstance(read, EvaluationRefSugar)
    assert read.deferred is True
    with pytest.raises(SugarNotWritten):
        read.desugar(_root("walrus-after-generator"))


# ---------------------------------------------------------------------------
# 4. An empty finite comprehension: the prior binding
# ---------------------------------------------------------------------------


def test_an_empty_comprehension_carries_the_prior_binding() -> None:
    rewritten = _function(
        "def f():\n    n = 7\n    [(n := v) for v in []]\n    return n\n"
    ).substitute({})
    (walrus,) = _walruses(rewritten)
    comprehension = _comprehension(rewritten, "ListComp")
    carried = _value(comprehension.sugar().desugar(_root("walrus-empty")))
    binds, presented = peel_walrus_binds(carried)
    assert presented.finite_elements == ()
    assert [(bind.name, bind.evaluation, bind.assigned_value) for bind in binds] == [
        ("n", walrus.evaluation, TermValue(7))
    ]


def test_a_read_after_an_empty_comprehension_is_the_prior_binding() -> None:
    returned = _returned_value(
        _call_outcome(
            "def f():\n"
            "    n = 7\n"
            "    [(n := v) for v in []]\n"
            "    return n\n"
            "\n"
            "f()\n"
        )
    )
    assert returned == TermValue(7)


def test_an_unbound_prior_carries_no_write() -> None:
    # `n` had no binding before: no member wrote, and there is no prior to
    # keep, so nothing is carried and a read after is refused by name.
    rewritten = _function(
        "def f():\n    [(n := v) for v in []]\n    return n\n"
    ).substitute({})
    comprehension = _comprehension(rewritten, "ListComp")
    carried = _value(comprehension.sugar().desugar(_root("walrus-unbound")))
    binds, _presented = peel_walrus_binds(carried)
    assert binds == ()
