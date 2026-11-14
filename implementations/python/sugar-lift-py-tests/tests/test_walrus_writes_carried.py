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
5. A read inside a comprehension of a name its walrus writes reads the
   members' recurrence: the binding before the comprehension for the first
   member, the previous member's write for every later one
   (``[(s := s + x) for x in [1, 2, 3]]`` after ``s = 0`` is ``[1, 3, 6]``,
   never ``[1, 2, 3]``).  Two walruses of one name compose in evaluation
   order within each member.  Where the recurrence is not held (a symbolic
   iterable, a read after a walrus of the name in the same condition) the
   read is refused by name.
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


# ---------------------------------------------------------------------------
# 5. A read inside the comprehension reads the members' recurrence
# ---------------------------------------------------------------------------

_RUNNING = "def f():\n    s = 0\n    ys = [(s := s + x) for x in [1, 2, 3]]\n    return s\n"
_TWO = (
    "def f():\n"
    "    s = 0\n"
    "    ys = [(s := s + x) for x in [1, 2, 3] if (s := s * 10) >= 0]\n"
    "    return s\n"
)


def test_a_read_inside_a_comprehension_reads_its_running_value() -> None:
    rewritten = _function(_RUNNING).substitute({})
    (walrus,) = _walruses(rewritten)
    reads = [
        node
        for node in walrus.value.walk()
        if node.kind == "EvaluationRef" and node.name == "s"
    ]
    # Not the `s = 0` binding substituted in: a reference to the running
    # value the comprehension binds.
    assert len(reads) == 1
    assert getattr(reads[0], "recurrence", False) is True
    assert getattr(reads[0], "member", False) is True
    comprehension = _comprehension(rewritten, "ListComp")
    ((name, coordinate, ordered),) = comprehension.sugar().walrus_recurrence
    assert (name, ordered) == ("s", True)
    assert reads[0].evaluation == coordinate


def test_the_running_sum_reads_the_previous_members_write() -> None:
    rewritten = _function(_RUNNING).substitute({})
    (walrus,) = _walruses(rewritten)
    comprehension = _comprehension(rewritten, "ListComp")
    carried = _value(comprehension.sugar().desugar(_root("walrus-running")))
    binds, presented = peel_walrus_binds(carried)
    assert presented.finite_elements == (TermValue(1), TermValue(3), TermValue(6))
    # Never every member reading `s = 0`.
    assert presented.finite_elements != (TermValue(1), TermValue(2), TermValue(3))
    assert [(bind.name, bind.evaluation, bind.assigned_value) for bind in binds] == [
        ("s", walrus.evaluation, TermValue(6))
    ]


def test_a_read_after_the_running_sum_is_its_last_write() -> None:
    returned = _returned_value(_call_outcome(_RUNNING + "\nf()\n"))
    assert returned == TermValue(6)


def test_two_walruses_of_one_name_compose_in_evaluation_order() -> None:
    rewritten = _function(_TWO).substitute({})
    walruses = _walruses(rewritten)
    assert len(walruses) == 2
    comprehension = _comprehension(rewritten, "ListComp")
    carried = _value(comprehension.sugar().desugar(_root("walrus-two")))
    binds, presented = peel_walrus_binds(carried)
    # Each member: the condition multiplies what the previous member left,
    # then the element adds to the condition's write.
    assert presented.finite_elements == (
        TermValue(1),
        TermValue(12),
        TermValue(123),
    )
    # Both walruses write `s`: each key holds the name's last write.
    assert len(binds) == 2
    assert {bind.evaluation for bind in binds} == {
        walrus.evaluation for walrus in walruses
    }
    assert all(bind.assigned_value == TermValue(123) for bind in binds)


def test_a_read_after_two_walruses_of_one_name_is_the_last_write() -> None:
    returned = _returned_value(_call_outcome(_TWO + "\nf()\n"))
    assert returned == TermValue(123)


def test_two_walruses_of_one_name_over_a_symbolic_iterable_carry_one_write() -> None:
    rewritten = _function(
        "def f(xs):\n"
        "    n = 0\n"
        "    ys = [(n := x) for x in xs if (n := x) > 0]\n"
        "    return n\n"
    ).substitute({})
    walruses = _walruses(rewritten)
    comprehension = _comprehension(rewritten, "ListComp")
    carried = _value(comprehension.sugar().desugar(_root("walrus-two-symbolic")))
    binds, presented = peel_walrus_binds(carried)
    assert presented.finite_elements is None
    # No longer refused: one guarded last write of `n`, under both keys.
    assert {bind.evaluation for bind in binds} == {
        walrus.evaluation for walrus in walruses
    }
    first, second = binds
    assert first.assigned_value == second.assigned_value
    written = first.assigned_value
    assert isinstance(written, GuardedValue)
    assert written.when_false == TermValue(0)
    last = written.when_true.to_term(owner="walrus-two-symbolic")
    assert last.name == "python:comprehension.last_write"
    # The condition's writes, then the element's, member by member.
    assert len(last.args) == 2


def test_a_running_read_over_a_symbolic_iterable_is_refused_by_name() -> None:
    rewritten = _function(
        "def f(xs):\n    s = 0\n    ys = [(s := s + x) for x in xs]\n    return s\n"
    ).substitute({})
    comprehension = _comprehension(rewritten, "ListComp")
    # Each member would read the previous member's write: the fold over a
    # symbolic member does not hold it, and it never reads `s = 0` instead.
    with pytest.raises(SugarNotWritten):
        comprehension.sugar().desugar(_root("walrus-running-symbolic"))


def test_a_read_after_the_members_own_write_over_a_symbolic_iterable() -> None:
    rewritten = _function(
        "def f(xs):\n    return [y for x in xs if (y := x) > 0]\n"
    ).substitute({})
    comprehension = _comprehension(rewritten, "ListComp")
    # The element reads the condition's write of the same member.
    carried = _value(comprehension.sugar().desugar(_root("walrus-member-symbolic")))
    _binds, presented = peel_walrus_binds(carried)
    assert isinstance(presented, ComprehensionValue)
    assert presented.finite_elements is None


def test_a_read_after_a_walrus_in_the_same_condition_is_refused_by_name() -> None:
    rewritten = _function(
        "def f():\n    return [y for x in [1, 2] if (y := x) and y > 0]\n"
    ).substitute({})
    comprehension = _comprehension(rewritten, "ListComp")
    sugar = comprehension.sugar()
    # One condition is evaluated whole before its write is applied: the
    # read of `y` after the walrus would see a stale value.
    ((name, _coordinate, ordered),) = sugar.walrus_recurrence
    assert (name, ordered) == ("y", False)
    with pytest.raises(SugarNotWritten):
        sugar.desugar(_root("walrus-unordered"))
