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
from sugar_lift_py_tests.floor.named_expression_value import carry_caller_stores
from sugar_lift_py_tests.sugar.assign_sugar import (
    AssignSugar,
    ChainedAssignSugar,
    MultiAssignSugar,
    UnpackStoreAssignSugar,
)
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


@dataclass(frozen=True)
class _LeaksAsOperand(ConstructedTermSugar):
    """An expression that halts at its head, offering no record (a
    subscript's ``KeyError``)."""

    site: object = field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        return ExitSet.halted(_effect())

    def to_term(self, *, owner: str):
        raise NotImplementedError(owner)


def test_a_later_members_halt_carries_the_walrus_an_earlier_member_bound() -> None:
    # ``x, y = (a := 1), <halts>``: ``a`` is bound when the second member
    # halts (no target is yet). The halt's record holds the bind, after the
    # block's prefix; it used to offer none, and the prefix (from before
    # ``a`` was bound) stood in for it.
    ctx = ReduceContext.root(owner="every-halt-record.walrus")
    before = _ReducedBlock((TermValue(7),), True, (), context=ctx)
    statement = MultiAssignSugar((("x", _walrus()), ("y", _LeaksAsOperand())), None)
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


# -- no target is bound before every right-hand side has completed --------------

_X_KEY = EVALUATION_PREFIX + "every-halt-record.target.x"
_Y_KEY = EVALUATION_PREFIX + "every-halt-record.target.y"


@dataclass(frozen=True)
class _HaltsWhereItRuns(ConstructedTermSugar):
    """An expression that halts carrying the record of the context it was
    evaluated in, as a call's halt does (``at_the_call``)."""

    site: object = field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        return ExitSet.halted(_effect(), state=halt_record(ctx))

    def to_term(self, *, owner: str):
        raise NotImplementedError(owner)


def _targets_statement(second) -> MultiAssignSugar:
    """``x, y = 1, <second>``, each target bound under its key."""
    return MultiAssignSugar(
        (("x", _One()), ("y", second)),
        None,
        evaluations=(("x", _X_KEY), ("y", _Y_KEY)),
    )


def test_a_later_right_hand_sides_halt_carries_no_earlier_target() -> None:
    # Python evaluates the whole right side, then assigns the targets: when
    # the second member halts, ``x`` is not assigned. The halt's record (the
    # context the member was evaluated in) holds no binding of ``x``; it
    # used to, since ``x`` was bound as soon as its member completed.
    ctx = ReduceContext.root(owner="every-halt-record.targets-halt")
    before = _ReducedBlock((TermValue(7),), True, (), context=ctx)
    exits = reduce_block_to_exitset(
        (_targets_statement(_HaltsWhereItRuns()),), ctx, after=before
    )
    halts = [exit_ for exit_ in exits.exits if isinstance(exit_, Halted)]
    assert halts
    for halt in halts:
        assert isinstance(halt.state, _ReducedBlock)
        assert halt.state.entries == (TermValue(7),)
        assert halt.state.context.temporal.value_if_bound(_X_KEY) != TermValue(1)


def test_every_target_is_bound_once_the_right_side_completed() -> None:
    # The completed twin: both targets are bound after the statement.
    ctx = ReduceContext.root(owner="every-halt-record.targets-complete")
    exits = reduce_block_to_exitset((_targets_statement(_One()),), ctx)
    (completed,) = [exit_ for exit_ in exits.exits if isinstance(exit_, Completed)]
    assert completed.value.context.temporal.value_if_bound(_X_KEY) == TermValue(1)
    assert completed.value.context.temporal.value_if_bound(_Y_KEY) == TermValue(1)


# -- every operand's halt carries the walrus binds made before it ----------------


@dataclass(frozen=True)
class _Pair(ConstructedTermSugar):
    """``first`` then ``second``, the second evaluated in the context the
    first wrote, both consumed by one step (as ``BoolOpSugar`` evaluates
    ``(a := f()) and g()``)."""

    first: Sugar
    second: Sugar
    site: object = field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        from sugar_lift_py_tests.floor.named_expression_value import (
            consume_operands,
            written_by,
        )

        return self.first.desugar(ctx).and_then(
            lambda first: self.second.desugar(written_by(first, ctx)).and_then(
                lambda second: consume_operands(
                    lambda _first, presented: ExitSet.completed(presented),
                    first,
                    second,
                )
            )
        )

    def to_term(self, *, owner: str):
        raise NotImplementedError(owner)


def test_an_operand_after_a_walrus_halts_with_the_walrus_bound() -> None:
    # ``(a := 1) and <halts>``: the halt's record is where the second
    # operand was evaluated, ``a`` bound -- the one expression evaluation
    # records it, whatever statement runs the expression (an ``if`` test, a
    # loop's iterable, a ``match`` subject, a ``with`` item, a ``return``).
    ctx = ReduceContext.root(owner="every-halt-record.operand")
    (halt,) = [
        exit_
        for exit_ in _Pair(_walrus(), _LeaksAsOperand()).desugar(ctx).exits
        if isinstance(exit_, Halted)
    ]
    assert isinstance(halt.state, _ReducedBlock)
    assert halt.state.entries == ()
    assert halt.state.context.temporal.value_if_bound(_WALRUS_KEY) == TermValue(1)


def test_an_operand_of_a_walrus_free_expression_halts_as_it_did() -> None:
    # No walrus: nothing is bound before the halt, which is handed on with
    # no record for its statement to record at its head.
    ctx = ReduceContext.root(owner="every-halt-record.operand-free")
    (halt,) = [
        exit_
        for exit_ in _Pair(_One(), _LeaksAsOperand()).desugar(ctx).exits
        if isinstance(exit_, Halted)
    ]
    assert halt.state is None


def test_a_statement_whose_operand_halts_after_a_nested_walrus_is_recorded() -> (
    None
):
    # ``x = (a := 1) and <halts>``: the right-hand side holds the walrus, so
    # the assignment had no record for the halt and was refused; the
    # operand's evaluation now records it with ``a`` bound.
    ctx = ReduceContext.root(owner="every-halt-record.operand-statement")
    before = _ReducedBlock((TermValue(7),), True, (), context=ctx)
    statement = AssignSugar("x", _Pair(_walrus(), _LeaksAsOperand()), None)
    exits = reduce_block_to_exitset((statement,), ctx, after=before)
    (halt,) = [exit_ for exit_ in exits.exits if isinstance(exit_, Halted)]
    assert halt.state.entries == (TermValue(7),)
    assert halt.state.context.temporal.value_if_bound(_WALRUS_KEY) == TermValue(1)


@dataclass(frozen=True)
class _ConsumesThenHalts(ConstructedTermSugar):
    """An expression whose step halts, offering no record, after its operand
    completed (``(a := 1) + 'x'``'s ``TypeError``)."""

    operand: Sugar
    site: object = field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        from sugar_lift_py_tests.floor.named_expression_value import (
            consume_operands,
        )

        return self.operand.desugar(ctx).and_then(
            lambda value: consume_operands(
                lambda _presented: ExitSet.halted(_effect("TypeError")), value
            )
        )

    def to_term(self, *, owner: str):
        raise NotImplementedError(owner)


def test_a_step_after_a_walrus_operand_halts_with_the_walrus_bound() -> None:
    # The step ran after its operand bound ``a``: its halt carries ``a``,
    # where it used to carry none of it (and the statement was refused).
    ctx = ReduceContext.root(owner="every-halt-record.step")
    before = _ReducedBlock((TermValue(7),), True, (), context=ctx)
    statement = AssignSugar("x", _ConsumesThenHalts(_walrus()), None)
    exits = reduce_block_to_exitset((statement,), ctx, after=before)
    (halt,) = [exit_ for exit_ in exits.exits if isinstance(exit_, Halted)]
    assert halt.state.entries == (TermValue(7),)
    assert halt.state.context.temporal.value_if_bound(_WALRUS_KEY) == TermValue(1)


def test_a_step_with_no_walrus_operand_halts_as_it_did() -> None:
    ctx = ReduceContext.root(owner="every-halt-record.step-free")
    (halt,) = [
        exit_
        for exit_ in _ConsumesThenHalts(_One()).desugar(ctx).exits
        if isinstance(exit_, Halted)
    ]
    assert halt.state is None


def _walrus_test(statement: str, second: str) -> str:
    """``f``: ``statement`` (holding ``(a := 1) and <second>``) inside a
    ``try`` whose handler (and the completed path) returns ``a``."""
    return (
        _RAISES
        + "def f():\n"
        + "    try:\n"
        + statement.format(test=f"(a := 1) and {second}")
        + "    except ValueError:\n"
        + "        return a\n"
        + "    return a\n"
    )


@pytest.mark.parametrize(
    "statement",
    [
        "        if {test}:\n            pass\n",
        "        assert {test}\n",
    ],
    ids=["if-test", "assert-test"],
)
def test_a_handler_sees_the_walrus_a_statements_test_bound_before_it_raised(
    statement: str,
) -> None:
    # ``if (a := 1) and g():`` where ``g`` raises: ``a`` is bound before
    # ``g()`` runs, and the handler returns it as the completed twin does.
    def returned(second: str):
        source = _walrus_test(statement, second)
        return _returned_value(function_universe_outcome(_function(source)))

    assert returned("g()") == returned("2")


# -- an unpack carries the walrus bound in its right-hand side -------------------


def _unpack_of_walrus(rhs: str, read: str) -> str:
    """``f``: ``x, y = (a := <rhs>)`` inside a ``try`` whose handler (and
    the completed path) returns ``read``."""
    return (
        "def f():\n"
        + "    try:\n"
        + f"        x, y = (a := {rhs})\n"
        + "    except ValueError:\n"
        + f"        return {read}\n"
        + f"    return {read}\n"
    )


def _returned_by(rhs: str, read: str):
    source = _unpack_of_walrus(rhs, read)
    return _returned_value(function_universe_outcome(_function(source)))


def test_an_unpack_of_a_walrus_binds_its_targets_and_the_walrus() -> None:
    # ``x, y = (a := (1, 2))`` binds ``x``, ``y`` and ``a``: ``y`` and
    # ``a[1]`` read the same member. It used to be refused: the unpack was
    # handed the walrus's value, not the value it presents.
    assert _returned_by("(1, 2)", "y") == _returned_by("(1, 2)", "a[1]")


def test_an_unpack_that_fails_after_its_walrus_carries_it() -> None:
    # ``x, y = (a := (1, 2, 3))`` raises ``ValueError`` after ``a`` is bound:
    # the handler reads ``a`` as the completed twin does.
    assert _returned_by("(1, 2, 3)", "a[0]") == _returned_by("(1, 2)", "a[0]")


# -- an assert's message runs before the assert fails --------------------------


def test_an_asserts_message_walrus_is_held() -> None:
    # The message is provenance, never reduced, and held out of equality; a
    # walrus in it still runs before ``AssertionError``, so the statement
    # holds it, and its record-less failure is refused, never given the
    # prefix that drops the bind.
    assert holds_a_walrus(AssertSugar(_One(), None, message_holds_a_walrus=True))
    assert not holds_a_walrus(AssertSugar(_One(), None))


def test_an_assert_built_from_source_says_its_message_holds_a_walrus() -> None:
    from sugar_source_tree.nodes import Assert

    def built(source: str) -> AssertSugar:
        context = TreeConstructionContextV1.for_source_call_construction()
        tree = SourceFile(
            (source, "every_halt_record.py", blake3_512_of(source.encode())),
            construction_context=context,
        )
        node = next(node for node in tree.nodes() if isinstance(node, Assert))
        return node._construct_sugar()

    assert built("def f():\n    assert True, (m := 'x')\n").message_holds_a_walrus
    assert not built("def f():\n    assert True, 'x'\n").message_holds_a_walrus
    assert not built("def f():\n    assert True\n").message_holds_a_walrus


# -- the targets are assigned left to right, stores among them -------------------

_VALUE_KEY = EVALUATION_PREFIX + "every-halt-record.target.value"
_MEMBER_KEY = EVALUATION_PREFIX + "every-halt-record.target.member"


@dataclass(frozen=True)
class _StoresHere(Sugar):
    """A store target's statement that completes, carrying the block on in
    the context it was handed."""

    site: object = field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        return ExitSet.completed(_ReducedBlock((), True, (), context=ctx))


def _chain(store) -> ChainedAssignSugar:
    """``x = o.a = y = 1``: ``store`` is ``o.a``'s statement."""
    one = _One()
    return ChainedAssignSugar(
        bindings=(("x", one), ("y", one)),
        stores=(store,),
        value=one,
        site=None,
        evaluations=(("x", _X_KEY), ("y", _Y_KEY)),
        evaluation=_VALUE_KEY,
        target_order=("x", 0, "y"),
    )


def _unpack(store) -> UnpackStoreAssignSugar:
    """``o.a, y = 1, 1``: ``store`` is ``o.a``'s statement."""
    return UnpackStoreAssignSugar(
        bindings=(("y", _One()),),
        stores=(store,),
        site=None,
        evaluations=(("y", _Y_KEY),),
        members=((_MEMBER_KEY, _One()),),
        target_order=(0, "y"),
    )


def test_a_store_targets_halt_holds_the_names_to_its_left_and_none_to_its_right() -> (
    None
):
    # ``x = o.a = y = 1`` where ``o.a`` raises: Python assigned ``x`` and
    # never ``y``. The halt's record binds ``x`` (and the value the store
    # read) and not ``y``; it used to bind ``y`` too, since every Name
    # target was bound before any store ran.
    ctx = ReduceContext.root(owner="every-halt-record.store-order")
    before = _ReducedBlock((TermValue(7),), True, (), context=ctx)
    exits = reduce_block_to_exitset((_chain(_HaltsAtHead()),), ctx, after=before)
    (halt,) = [exit_ for exit_ in exits.exits if isinstance(exit_, Halted)]
    assert halt.state.entries == (TermValue(7),)
    temporal = halt.state.context.temporal
    assert temporal.value_if_bound(_VALUE_KEY) == TermValue(1)
    assert temporal.value_if_bound(_X_KEY) == TermValue(1)
    assert temporal.value_if_bound(_Y_KEY) is None


def test_an_unpacks_store_leaf_halts_before_the_name_to_its_right() -> None:
    # ``o.a, y = 1, 1`` where ``o.a`` raises: ``y`` is never assigned.
    ctx = ReduceContext.root(owner="every-halt-record.unpack-order")
    before = _ReducedBlock((TermValue(7),), True, (), context=ctx)
    exits = reduce_block_to_exitset((_unpack(_HaltsAtHead()),), ctx, after=before)
    (halt,) = [exit_ for exit_ in exits.exits if isinstance(exit_, Halted)]
    assert halt.state.entries == (TermValue(7),)
    temporal = halt.state.context.temporal
    assert temporal.value_if_bound(_MEMBER_KEY) == TermValue(1)
    assert temporal.value_if_bound(_Y_KEY) is None


@pytest.mark.parametrize("statement", [_chain, _unpack], ids=["chain", "unpack"])
def test_every_target_around_a_completed_store_is_assigned(statement) -> None:
    # The completed twin: every Name target is bound after the statement.
    ctx = ReduceContext.root(owner="every-halt-record.store-order-complete")
    exits = reduce_block_to_exitset((statement(_StoresHere()),), ctx)
    (completed,) = [exit_ for exit_ in exits.exits if isinstance(exit_, Completed)]
    assert completed.value.context.temporal.value_if_bound(_Y_KEY) == TermValue(1)


# -- a statement's own step after a walrus records its halt ----------------------


def _raises_after_walrus(statement: str, caught: str) -> str:
    """``f``: ``statement`` inside a ``try`` whose ``caught`` handler (and
    the completed path) returns ``a``."""
    return (
        "def f():\n"
        + "    try:\n"
        + statement
        + f"    except {caught}:\n"
        + "        return a\n"
        + "    return a\n"
    )


def _returned_after(statement: str, caught: str):
    source = _raises_after_walrus(statement, caught)
    return _returned_value(function_universe_outcome(_function(source)))


def test_a_raise_of_a_walrus_value_carries_the_bind() -> None:
    # ``raise ValueError((a := 1))``: ``a`` is bound before the raise. The
    # raise's halt carries the bind (its operand is its header,
    # ``header_applied``), and the handler reads ``a`` as it does when the
    # walrus ran in a statement of its own.
    assert _returned_after(
        "        raise ValueError((a := 1))\n", "ValueError"
    ) == _returned_after("        (a := 1)\n        raise ValueError()\n", "ValueError")


def test_a_failing_assert_carries_its_tests_walrus() -> None:
    # ``assert (a := 1) == 2`` fails after ``a`` is bound: the handler reads
    # ``a`` as the passing twin's completed path does.
    assert _returned_after(
        "        assert (a := 1) == 2\n", "AssertionError"
    ) == _returned_after("        assert (a := 1) == 1\n", "AssertionError")


# -- an operation on a walrus's value halts with the walrus bound ----------------


class _TruthRaises(TermValue):
    """A value whose truth raises, offering no record (``__bool__``)."""

    def truth(self, site):
        return ExitSet.halted(_effect("TypeError"))


@dataclass(frozen=True)
class _Presents(ConstructedTermSugar):
    """An expression completing with ``value``."""

    value: object
    site: object = field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        return ExitSet.completed(self.value)

    def to_term(self, *, owner: str):
        raise NotImplementedError(owner)


@dataclass(frozen=True)
class _TruthOf(ConstructedTermSugar):
    """Asks the truth of its operand's value itself, as a short-circuit or
    a test does (no operand door between them)."""

    operand: Sugar
    site: object = field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        return self.operand.desugar(ctx).and_then(lambda value: value.truth(self.site))

    def to_term(self, *, owner: str):
        raise NotImplementedError(owner)


def _walrus_over(value) -> NamedExprSugar:
    """``(a := <value>)``, bound under ``_WALRUS_KEY``."""
    return NamedExprSugar("a", _Presents(value), None, evaluation=_WALRUS_KEY)


def test_the_truth_of_a_walrus_value_halts_with_the_walrus_bound() -> None:
    # ``x = bool((a := v))`` where ``v.__bool__`` raises: the walrus bound
    # ``a`` before its value's truth ran, inside the sugar that asked it.
    # The halt used to offer no record (and the statement, holding the
    # walrus, was refused); it now carries ``a``.
    ctx = ReduceContext.root(owner="every-halt-record.walrus-truth")
    before = _ReducedBlock((TermValue(7),), True, (), context=ctx)
    statement = AssignSugar("x", _TruthOf(_walrus_over(_TruthRaises(1))), None)
    exits = reduce_block_to_exitset((statement,), ctx, after=before)
    (halt,) = [exit_ for exit_ in exits.exits if isinstance(exit_, Halted)]
    assert halt.state.entries == (TermValue(7),)
    assert halt.state.context.temporal.value_if_bound(_WALRUS_KEY) == _TruthRaises(1)


def test_the_truth_of_a_value_with_no_walrus_halts_as_it_did() -> None:
    ctx = ReduceContext.root(owner="every-halt-record.truth-free")
    (halt,) = [
        exit_
        for exit_ in _TruthOf(_Presents(_TruthRaises(1))).desugar(ctx).exits
        if isinstance(exit_, Halted)
    ]
    assert halt.state is None


# -- a callee's store is in the entries of every halt after it -------------------


@dataclass(frozen=True)
class _Store:
    """A store a callee made on an object its caller sees."""

    name: str

    def extend_scope(self, ctx):
        return ctx


_STORE = _Store("o.x")


def _carries_a_store() -> _Presents:
    """A call's value carrying ``_STORE`` (``CallerStoreValue``)."""
    return _Presents(carry_caller_stores((_STORE,), TermValue(1)))


def _halt_entries(statement):
    ctx = ReduceContext.root(owner="every-halt-record.store-entries")
    before = _ReducedBlock((TermValue(7),), True, (), context=ctx)
    exits = reduce_block_to_exitset((statement,), ctx, after=before)
    (halt,) = [exit_ for exit_ in exits.exits if isinstance(exit_, Halted)]
    return halt.state.entries


def test_a_step_after_a_callee_store_lays_it_in_its_halts_record() -> None:
    # ``x = f(o) + 'x'`` where ``f`` stores ``o.x``: the store happened
    # before the step raised. It used to ride the record's context alone.
    statement = AssignSugar("x", _ConsumesThenHalts(_carries_a_store()), None)
    assert _halt_entries(statement) == (TermValue(7), _STORE)


def test_a_later_right_hand_sides_halt_lays_an_earlier_ones_callee_store() -> None:
    # ``x, y = f(o), <halts>``: ``f``'s store is first in the halt's entries.
    statement = MultiAssignSugar(
        (("x", _carries_a_store()), ("y", _HaltsWhereItRuns())), None
    )
    assert _halt_entries(statement) == (TermValue(7), _STORE)


def test_a_store_targets_halt_lays_the_right_sides_callee_store() -> None:
    # ``x = o.a = y = f(o)`` where ``o.a`` raises: ``f``'s store came first.
    value = _carries_a_store()
    statement = ChainedAssignSugar(
        bindings=(("x", value), ("y", value)),
        stores=(_HaltsAtHead(),),
        value=value,
        site=None,
        evaluations=(("x", _X_KEY), ("y", _Y_KEY)),
        evaluation=_VALUE_KEY,
        target_order=("x", 0, "y"),
    )
    assert _halt_entries(statement) == (TermValue(7), _STORE)
