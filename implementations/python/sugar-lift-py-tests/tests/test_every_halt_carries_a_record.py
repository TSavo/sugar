"""Every halt carries a record, built by its producer (#7757, leftover of
#8100).

A halt's record is everything the block reached before it halted: every
store, rebind, container mutation and walrus bind, in its entries and in the
context it halted in. A compound statement's head -- an ``if`` test, a loop's
iterable, a ``with`` manager or enter, an ``assert`` test -- halts before
anything of the statement ran, so it carries the empty record where it halted
(``function_universe_sugar.halt_record``), and the block composition splices
what ran before the statement onto it. Such a halt used to carry ``None`` (or
a bare context), and ``resumed`` / ``LoopRecurrenceSugar._left_with`` made up
an empty record in the try's context in its place, dropping what ran before
the halt. They now refuse a state that is no record by name, and so does
``Halted`` itself as an arm is built: a halt's state is a record (or ``None``,
an expression's halt that its statement records), and whatever else it must
carry -- a generator frame -- lives inside that record.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import ClassVar

import pytest
from frame_fresh import fresh

from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.floor.list_value import ListValue
from sugar_lift_py_tests.ir import atomic, not_
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_py_tests.sugar.assert_sugar import AssertSugar
from sugar_lift_py_tests.sugar.assign_sugar import AssignSugar, MultiAssignSugar
from sugar_lift_py_tests.sugar.function_universe_sugar import (
    _ReducedBlock,
    face_record,
    halt_record,
    halts_recorded,
    reduce_block_to_exitset,
    resumed,
)
from sugar_lift_py_tests.sugar.if_sugar import IfSugar
from sugar_lift_py_tests.sugar.named_expr_sugar import NamedExprSugar, holds_a_walrus
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar, Sugar
from sugar_lift_py_tests.temporal.temporal_context import EVALUATION_PREFIX
from sugar_lift_py_tests.tree_enumerate import function_universe_outcome
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import FunctionDef
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _effect(name: str = "ValueError") -> RaiseEffect:
    return RaiseEffect.for_builtin(name, occurrence=f"every-halt-record:{name}")


# -- the law at the seams -------------------------------------------------------


def test_a_halt_record_holds_nothing_in_the_context_it_halted_in() -> None:
    ctx = ReduceContext.root(owner="every-halt-record")
    record = halt_record(ctx)
    assert isinstance(record, _ReducedBlock)
    assert record.entries == ()
    assert record.context is ctx


def test_a_halt_with_no_record_is_given_the_producers_and_keeps_its_arm() -> None:
    # A halt that offers no record carries the one handed; one that carries
    # its own (a call's halt: the callee's) keeps it; guards, faces and what
    # each arm owes are untouched.
    ctx = ReduceContext.root(owner="every-halt-record.recorded")
    own = _ReducedBlock((TermValue(3),), False, (), context=ctx)
    guard = atomic("test.halts", [])
    bare = Halted(guard, _effect(), None, owed=("owed.bare",))
    kept = Halted(not_(guard), _effect("KeyError"), own)
    record = halt_record(ctx)
    recorded = halts_recorded(ExitSet((bare, kept)), record)
    first, second = recorded.exits
    assert first.state is record
    assert first.guard == bare.guard and first.owed == bare.owed
    assert second is kept


@pytest.mark.parametrize(
    "state", [None, ReduceContext.root(owner="every-halt-record.bare"), "payload"]
)
def test_a_suite_never_resumes_from_a_state_that_is_no_record(state) -> None:
    # No empty record is made up in the halt's place: the refusal names it.
    with pytest.raises(SugarNotWritten) as refused:
        resumed(state, None, owner="test.resumed", blame="test")
    assert refused.value.owner == "test.resumed"


@pytest.mark.parametrize(
    "state",
    [ReduceContext.root(owner="every-halt-record.built"), "payload", TermValue(3)],
    ids=["bare-context", "payload", "value"],
)
def test_a_halt_whose_state_is_no_record_is_refused_as_it_is_built(state) -> None:
    # The check lives in ``Halted`` itself: no producer can build an arm whose
    # state is a bare context, a generator's machine or any other payload.
    with pytest.raises(SugarNotWritten) as refused:
        Halted(atomic("test.built", []), _effect(), state)
    assert refused.value.owner == "Halted"
    with pytest.raises(SugarNotWritten):
        ExitSet.halted(_effect(), state=state)


def test_a_halt_is_built_from_a_record_or_from_none() -> None:
    # A record, and ``None`` (an expression's halt, which the statement that
    # runs it records), are the two states an arm is built with.
    ctx = ReduceContext.root(owner="every-halt-record.admitted")
    record = halt_record(ctx)
    assert Halted(atomic("test.record", []), _effect(), record).state is record
    assert Halted(atomic("test.none", []), _effect(), None).state is None


def test_a_generator_frame_lives_inside_its_halts_record() -> None:
    # Whatever else a halt must carry (a generator frame) lives inside its
    # record, never in its place; it is a lookup aid, out of equality.
    ctx = ReduceContext.root(owner="every-halt-record.frame")
    frame = object()
    record = halt_record(ctx, frame=frame)
    assert isinstance(record, _ReducedBlock)
    assert record.frame is frame
    assert record.context is ctx
    assert record == halt_record(ctx)
    (halt,) = ExitSet.halted(_effect(), state=record).exits
    assert halt.state.frame is frame


def test_a_suite_resumes_from_the_records_entries_and_context_without_its_returns() -> (
    None
):
    # The one record a continuation after a halt starts from: the record's
    # entries in its context, every ``return`` entry dropped (dead on the
    # halt's arm), going on with no fall-through guard and no transform.
    from sugar_lift_py_tests.floor import GuardedReturn, ReturnValue

    ctx = ReduceContext.root(owner="every-halt-record.resumed")
    guard = atomic("test.resumed", [])
    state = _ReducedBlock(
        (
            TermValue(1),
            GuardedReturn((guard,), TermValue(2)),
            TermValue(3),
            ReturnValue(TermValue(4)),
        ),
        False,
        (not_(guard),),
        (lambda entries: entries,),
        context=ctx,
    )
    record = resumed(state, None, owner="test.resumed", blame="test")
    assert record.entries == (TermValue(1), TermValue(3))
    assert record.can_fall_through
    assert record.fall_through == ()
    assert record.transforms == ()
    assert record.context is ctx


def test_a_face_without_a_record_is_refused_by_name() -> None:
    bare = Halted(atomic("test.face", []), _effect(), None)
    with pytest.raises(SugarNotWritten) as refused:
        face_record(bare, owner="test.face", blame="test")
    assert refused.value.owner == "test.face"
    record = _ReducedBlock((TermValue(1),), True, ())
    assert face_record(
        Completed(atomic("test.face", []), record), owner="test.face", blame="test"
    ) is record


def test_an_assert_halts_at_the_head_of_its_statement() -> None:
    # An ``assert`` binds nothing before its own halt: the enclosing block's
    # prefix is its halt's record, as for every simple statement.
    assert AssertSugar.halts_at_statement_head


@dataclass(frozen=True)
class _NoTruth:
    """A completed condition face whose truth is not one value: it selects
    no suite (``IfSugar._select_on_face``) and carries the block on."""

    def truth(self, site):
        return ExitSet(())

    def contribution(self):
        return ()

    def follow_rest(self):
        return SimpleNamespace(continues=True, continuation_guard=None, transform=None)

    def extend_scope(self, ctx):
        return ctx


@dataclass(frozen=True)
class _MayRaise(Sugar):
    """A condition that completes under ``test.completes`` and raises,
    offering no record, under its negation (an expression's halt)."""

    site: object = field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        completes = atomic("test.completes", [])
        return ExitSet(
            (
                Completed(completes, _NoTruth()),
                Halted(not_(completes), _effect(), None),
            )
        )


def test_an_if_conditions_halt_carries_what_ran_before_the_if() -> None:
    # The condition halted before either suite ran: its halt carries the
    # record of where it halted, and the block composition splices what ran
    # before the ``if`` (``TermValue(7)``) onto it. It used to carry ``None``,
    # and the block left it alone: what ran before the ``if`` was dropped.
    ctx = ReduceContext.root(owner="every-halt-record.if")
    before = _ReducedBlock((TermValue(7),), True, (), context=ctx)
    exits = reduce_block_to_exitset(
        (IfSugar(_MayRaise(), None, (), ()),), ctx, after=before
    )
    (halt,) = [exit_ for exit_ in exits.exits if isinstance(exit_, Halted)]
    assert isinstance(halt.state, _ReducedBlock)
    assert halt.state.entries == (TermValue(7),)
    assert halt.state.context is ctx


# -- the boundary: ``None`` never leaves a statement ------------------------------


@dataclass(frozen=True)
class _Leaks(Sugar):
    """A statement that hands the block an expression's halt as it is: no
    record, and no declaration that it halted at its head."""

    guarded: bool = False
    site: object = field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        halted = ExitSet.halted(_effect())
        if self.guarded:
            return halted.guarded(atomic("test.leaks", []))
        return halted


@dataclass(frozen=True)
class _HaltsAtHead(_Leaks):
    """The same halt from a statement that binds nothing before it."""

    halts_at_statement_head: ClassVar[bool] = True


@pytest.mark.parametrize("guarded", [False, True], ids=["plain", "guarded"])
def test_the_block_refuses_a_statement_that_leaks_a_halt_with_no_record(
    guarded: bool,
) -> None:
    # ``None`` lives only inside an expression's evaluation: a statement that
    # hands it to the block reducer is stopped by name, never given the
    # block's prefix (which would drop what it bound first) and never let
    # through record-less.
    ctx = ReduceContext.root(owner="every-halt-record.leaks")
    before = _ReducedBlock((TermValue(7),), True, (), context=ctx)
    with pytest.raises(SugarNotWritten) as refused:
        reduce_block_to_exitset((_Leaks(guarded=guarded),), ctx, after=before)
    assert refused.value.owner == "reduce_block_to_exitset.statement"


@pytest.mark.parametrize("guarded", [False, True], ids=["plain", "guarded"])
def test_a_statement_that_halts_at_its_head_takes_the_blocks_prefix(
    guarded: bool,
) -> None:
    # A statement that binds nothing before its halt declares it: the
    # block's prefix is the halt's whole record.
    ctx = ReduceContext.root(owner="every-halt-record.head")
    before = _ReducedBlock((TermValue(7),), True, (), context=ctx)
    exits = reduce_block_to_exitset(
        (_HaltsAtHead(guarded=guarded),), ctx, after=before
    )
    (halt,) = [exit_ for exit_ in exits.exits if isinstance(exit_, Halted)]
    assert isinstance(halt.state, _ReducedBlock)
    assert halt.state.entries == (TermValue(7),)


# -- end to end: a handler sees what ran before the raise ------------------------


def _function(source: str) -> FunctionDef:
    tree = SourceFile(
        (source, "every_halt_record.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    return next(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name == "f"
    )


def _holds(entries, value) -> bool:
    """Whether ``entries`` (or a block nested in them) holds ``value``."""
    from sugar_lift_py_tests.floor.block_value import BlockValue

    pending = list(entries)
    while pending:
        entry = pending.pop()
        if entry == value:
            return True
        if isinstance(entry, BlockValue):
            pending.extend(entry.statements)
    return False


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


_ONE = fresh(ListValue, (TermValue(1),))

_RAISES = "def g():\n    raise ValueError()\n"

_MANAGER = (
    "class M:\n"
    "    def __enter__(self):\n"
    "        raise ValueError()\n"
    "    def __exit__(self, exc_type, exc, tb):\n"
    "        return False\n"
)

# Each raises at the head of a compound statement, after ``acc.append(1)``.
_HEADS = {
    "if-condition": (
        _RAISES,
        "    if g():\n        return 0\n",
    ),
    "loop-iterable": (
        _RAISES,
        "    for x in g():\n        acc.append(x)\n",
    ),
    "with-enter": (
        _MANAGER,
        "    with M():\n        acc.append(2)\n",
    ),
    "assert": (
        _RAISES,
        "    assert g()\n",
    ),
}


def _caught(helper: str, head: str) -> str:
    """``f``: ``acc.append(1)``, then ``head``, inside a ``try`` whose
    handler returns ``acc``."""
    indented = "".join("    " + line + "\n" for line in head.splitlines())
    prefix = "def f():\n    acc = []\n    try:\n        acc.append(1)\n"
    handler = "    except ValueError:\n        return acc\n    return None\n"
    return helper + prefix + indented + handler


def _uncaught(helper: str, head: str) -> str:
    """``f``: ``acc.append(1)``, then ``head``, with nothing to catch it."""
    prefix = "def f():\n    acc = []\n    acc.append(1)\n"
    return helper + prefix + head + "    return None\n"


@pytest.mark.parametrize("head", sorted(_HEADS))
def test_a_handler_sees_the_stores_made_before_a_raise_at_a_head(head: str) -> None:
    # The handler resumes from the halt's record: ``acc.append(1)`` ran
    # before the head raised, so the handler returns ``[1]``.
    helper, statement = _HEADS[head]
    outcome = function_universe_outcome(_function(_caught(helper, statement)))
    assert _returned_value(outcome) == _ONE


@pytest.mark.parametrize("head", sorted(_HEADS))
def test_every_halt_leaving_a_head_carries_a_record_with_what_ran_before(
    head: str,
) -> None:
    # The law: every halted arm the function leaves by carries a record, and
    # the record holds the append made before the head raised.
    helper, statement = _HEADS[head]
    outcome = function_universe_outcome(_function(_uncaught(helper, statement)))
    halts = [exit_ for exit_ in outcome.exits if isinstance(exit_, Halted)]
    assert halts, outcome
    for halt in halts:
        assert isinstance(halt.state, _ReducedBlock), halt
        assert _holds(halt.state.entries, _ONE), halt.state.entries


# -- a nested unpack: the inner halt carries what the outer targets bound ------


def _nested_unpack(second: str, read: str) -> str:
    """``f``: ``(a, b), (c, d) = pairs`` whose second member is ``second``;
    a handler for its ``ValueError`` (and the completed path) returns
    ``read``."""
    return (
        "def f():\n"
        f"    pairs = ((1, 2), {second})\n"
        "    try:\n"
        "        (a, b), (c, d) = pairs\n"
        "    except ValueError:\n"
        f"        return {read}\n"
        f"    return {read}\n"
    )


@pytest.mark.parametrize("read", ["a", "b"])
def test_a_nested_unpack_whose_inner_arity_fails_keeps_the_outer_binding(
    read: str,
) -> None:
    # CPython stores ``a`` and ``b`` before it unpacks ``(3, 4, 5)`` into
    # ``(c, d)`` and raises: the handler reads them as the completed path
    # would. The inner halt used to offer no record, and the statement's
    # prefix (from before ``a`` and ``b`` were bound) stood in for it.
    def returned(second: str):
        source = _nested_unpack(second, read)
        return _returned_value(function_universe_outcome(_function(source)))

    assert returned("(3, 4, 5)") == returned("(3, 4)")


# -- a walrus binds before a later operand halts ---------------------------------

_WALRUS_KEY = EVALUATION_PREFIX + "every-halt-record.walrus.a"


@dataclass(frozen=True)
class _One(ConstructedTermSugar):
    """The constant ``1``."""

    site: object = field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        return ExitSet.completed(TermValue(1))

    def to_term(self, *, owner: str):
        raise NotImplementedError(owner)


def _walrus() -> NamedExprSugar:
    """``(a := 1)``, bound under ``_WALRUS_KEY``."""
    return NamedExprSugar("a", _One(), None, evaluation=_WALRUS_KEY)


@dataclass(frozen=True)
class _HaltsAfterItsWalrus(Sugar):
    """An operand that runs a walrus and then halts, offering no record."""

    inner: Sugar
    site: object = field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        return ExitSet.halted(_effect())


def test_a_walrus_free_sugar_holds_no_walrus_and_one_that_runs_it_does() -> None:
    assert not holds_a_walrus(_Leaks())
    assert holds_a_walrus(_walrus())
    assert holds_a_walrus(_HaltsAfterItsWalrus(_walrus()))
    assert holds_a_walrus(MultiAssignSugar((("x", _walrus()), ("y", _Leaks())), None))


def test_a_later_members_halt_carries_the_walrus_an_earlier_member_bound() -> None:
    # ``x, y = (a := 1), <halts>``: ``a`` is bound when the second member
    # halts (no target is yet). The halt's record holds the bind, after the
    # block's prefix; it used to offer none, and the prefix (from before
    # ``a`` was bound) stood in for it.
    ctx = ReduceContext.root(owner="every-halt-record.walrus")
    before = _ReducedBlock((TermValue(7),), True, (), context=ctx)
    statement = MultiAssignSugar((("x", _walrus()), ("y", _Leaks())), None)
    exits = reduce_block_to_exitset((statement,), ctx, after=before)
    halts = [exit_ for exit_ in exits.exits if isinstance(exit_, Halted)]
    assert halts
    for halt in halts:
        assert isinstance(halt.state, _ReducedBlock)
        assert halt.state.entries == (TermValue(7),)
        assert halt.state.context.temporal.value_if_bound(_WALRUS_KEY) == TermValue(1)


def test_a_statement_holding_a_walrus_is_refused_a_halt_with_no_record() -> None:
    # The declaration that the statement binds nothing before a halt is
    # checked, not trusted: a walrus it holds may have bound first, so its
    # record-less halt is refused by name, never given the prefix.
    ctx = ReduceContext.root(owner="every-halt-record.walrus-refused")
    before = _ReducedBlock((TermValue(7),), True, (), context=ctx)
    statement = AssignSugar("x", _HaltsAfterItsWalrus(_walrus()), None)
    assert AssignSugar.halts_at_statement_head
    with pytest.raises(SugarNotWritten) as refused:
        reduce_block_to_exitset((statement,), ctx, after=before)
    assert refused.value.owner == "reduce_block_to_exitset.statement"


def test_a_statement_holding_no_walrus_halts_at_its_head() -> None:
    # The same statement with no walrus: the block's prefix is the record.
    ctx = ReduceContext.root(owner="every-halt-record.walrus-free")
    before = _ReducedBlock((TermValue(7),), True, (), context=ctx)
    exits = reduce_block_to_exitset(
        (AssignSugar("x", _Leaks(), None),), ctx, after=before
    )
    (halt,) = [exit_ for exit_ in exits.exits if isinstance(exit_, Halted)]
    assert isinstance(halt.state, _ReducedBlock)
    assert halt.state.entries == (TermValue(7),)


def _walrus_then(second: str) -> str:
    """``f``: ``x, y = (a := 1), <second>`` inside a ``try`` whose handler
    (and the completed path) returns ``a``."""
    return (
        _RAISES
        + "def f():\n"
        + "    try:\n"
        + f"        x, y = (a := 1), {second}\n"
        + "    except ValueError:\n"
        + "        return a\n"
        + "    return a\n"
    )


def test_a_handler_sees_the_walrus_bound_before_a_later_member_raised() -> None:
    # ``a`` is bound before ``g()`` raises: the handler returns it as the
    # completed twin does.
    def returned(second: str):
        source = _walrus_then(second)
        return _returned_value(function_universe_outcome(_function(source)))

    assert returned("g()") == returned("2")
