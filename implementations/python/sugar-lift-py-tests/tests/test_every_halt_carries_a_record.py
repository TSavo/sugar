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
    """A completed condition face whose truth has no arm: taken through the
    one truth rule (``IfSugar._desugar_condition``), it selects no suite."""

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


def _returned_value(outcome, *, under_a_decided_test: bool = False):
    from sugar_lift_py_tests.floor.guarded_return import GuardedReturn
    from sugar_lift_py_tests.floor.return_value import ReturnValue
    from sugar_lift_py_tests.floor.universe_value import UniverseValue

    from sugar_lift_py_tests.floor.block_value import BlockValue

    universe = outcome.completed_value()
    assert isinstance(universe, UniverseValue), outcome
    # The one return the completed arm took, at any depth: a statement whose
    # suite the reduction decided (``if (a := 1) and 2:``) records its
    # suite's block, and what follows it, nested (``_holds`` reads the same
    # nesting).  Exactly one: a second return on the arm is a wrong record.
    # Nested under the decided ``if``, what follows it is guarded by the
    # test's truth (``BlockValue.guarded``), so its ``return`` is a
    # ``GuardedReturn``; ``under_a_decided_test`` reads that one too.
    kinds = (ReturnValue, GuardedReturn) if under_a_decided_test else (ReturnValue,)
    returns = []
    pending = list(universe.record.statements)
    while pending:
        entry = pending.pop()
        if isinstance(entry, kinds):
            returns.append(entry)
        elif isinstance(entry, BlockValue):
            pending.extend(entry.statements)
    (returned,) = returns
    return returned.value


_ONE = fresh(ListValue, (TermValue(1),))

# The raise at a head is ``int("x")``: a builtin the reduction decides over
# its ground operand, ``ValueError`` always.  These heads raised through a
# same-file ``g()`` (and a same-file manager's ``__enter__``) until #7757
# steps 5 and 6 (#8705, #8744): a same-file call is its coordinate and edge,
# whose raise is joined at prove (the handler's match by the callee's stated
# halt type, #8749), never decided at the reduction, so the state a halt at
# the head carries could no longer be read off which handler ran.
_RAISE = 'int("x")'

_MANAGER = (
    "class M:\n"
    "    def __init__(self, v):\n"
    "        pass\n"
    "    def __enter__(self):\n"
    "        return self\n"
    "    def __exit__(self, exc_type, exc, tb):\n"
    "        return False\n"
)

# Each raises at the head of a compound statement, after ``acc.append(1)``.
# The ``with``'s head raises in its manager's actual, before ``M`` is called.
_HEADS = {
    "if-condition": (
        "",
        f"    if {_RAISE}:\n        return 0\n",
    ),
    "loop-iterable": (
        "",
        f"    for x in {_RAISE}:\n        acc.append(x)\n",
    ),
    "with-manager": (
        _MANAGER,
        f"    with M({_RAISE}):\n        acc.append(2)\n",
    ),
    "assert": (
        "",
        f"    assert {_RAISE}\n",
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


# A ``for`` (live loop) or a ``with`` gave the enclosing ``try`` one halt edge
# for the whole statement: a halt in its header (the iterable, ``__enter__``)
# was joined with the halts of its body, which append to ``acc``, so the
# handler read ``acc`` undecided although no body code ran when the header
# raised.  The header has an edge of its own now (``Try._body_halt_edges``,
# ``_header_halt_state``), named by the halt's occurrence
# (``_header_occurrence_keys``).  A same-file manager's ``__enter__`` is a
# method call, coordinate and edge, since #8744: its raise is joined at prove,
# so the ``with`` head here raises in the manager expression instead.
_HEADER_EDGE_HEADS = ("loop-iterable", "with-manager")


@pytest.mark.parametrize("head", _HEADER_EDGE_HEADS)
def test_the_truthful_half_returns_the_state_at_the_header_that_raised(
    head: str,
) -> None:
    # TRUTHFUL: ``acc.append(1)`` ran, then the header raised before the
    # body; the handler returns ``[1]``.
    outcome = function_universe_outcome(_function(_caught(*_HEADS[head])))
    assert _returned_value(outcome) == _ONE


@pytest.mark.parametrize("head", _HEADER_EDGE_HEADS)
def test_the_lying_half_reads_acc_as_the_body_may_have_left_it(head: str) -> None:
    # LYING: ``acc`` undecided at the handler (the header's halt joined with
    # the body's), or holding what the body appends.
    returned = _returned_value(
        function_universe_outcome(_function(_caught(*_HEADS[head])))
    )
    assert isinstance(returned, ListValue), returned
    assert returned.elements[1:] == (), returned


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


# The unpack's statement holds only names, tuples and the assignment, so it
# was read as a statement that cannot halt: it gave the ``try`` no halt edge,
# and the handler began from the bindings standing before the whole
# statement, where ``a`` is unbound.  It is a halt edge now
# (``Try._statement_cannot_halt``, ``_unpack_may_raise``), carrying the read
# of ``a`` at the halt, which the inner level's record binds.
_NESTED_UNPACK_RAISES = _nested_unpack("(3, 4, 5)", "a")


def test_the_truthful_half_reads_the_outer_leaf_bound_before_the_raise() -> None:
    # TRUTHFUL: Python stores ``a = 1`` and ``b = 2``, then unpacking
    # ``(3, 4, 5)`` into ``(c, d)`` raises; the handler returns 1.
    outcome = function_universe_outcome(_function(_NESTED_UNPACK_RAISES))
    assert _returned_value(outcome) == TermValue(1)


def test_the_lying_half_raises_name_error_for_the_outer_leaf() -> None:
    # LYING: every arm a ``NameError`` for ``a``, read where the handler
    # began from the bindings before the unpack.
    from sugar_lift_py_tests.effect import NameErrorEffect

    outcome = function_universe_outcome(_function(_NESTED_UNPACK_RAISES))
    assert not any(
        isinstance(exit_, Halted) and isinstance(exit_.effect, NameErrorEffect)
        for exit_ in outcome.exits
    ), outcome


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
        "def f():\n"
        + "    try:\n"
        + f"        x, y = (a := 1), {second}\n"
        + "    except ValueError:\n"
        + "        return a\n"
        + "    return a\n"
    )


def test_a_handler_sees_the_walrus_bound_before_a_later_member_raised() -> None:
    # ``a`` is bound before ``int("x")`` raises: the handler returns it as
    # the completed twin does.
    def returned(second: str):
        source = _walrus_then(second)
        return _returned_value(function_universe_outcome(_function(source)))

    assert returned(_RAISE) == returned("2")


# -- no target is bound before every right-hand side has completed --------------

_X_KEY = EVALUATION_PREFIX + "every-halt-record.target.x"
_Y_KEY = EVALUATION_PREFIX + "every-halt-record.target.y"


@dataclass(frozen=True)
class _HaltsWhereItRuns(ConstructedTermSugar):
    """An expression that halts carrying the record of the context it was
    evaluated in."""

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
        "def f():\n"
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
    # ``if (a := 1) and int("x"):``, which raises: ``a`` is bound before
    # ``int("x")`` runs, and the handler returns it as the completed twin
    # does.  With ``2`` the ``if`` test is decided at the reduction, and the
    # ``return a`` after the ``try`` is recorded nested under it, guarded by
    # the test's truth (a ``GuardedReturn``); the value is the same ``a``.
    def returned(second: str):
        source = _walrus_test(statement, second)
        return _returned_value(
            function_universe_outcome(_function(source)), under_a_decided_test=True
        )

    assert returned(_RAISE) == returned("2")


# A compound statement's halt in its header carried the state the header left
# with every name unbound before the statement dropped
# (``Try._mid_statement_state`` read a compound statement's names as unknown
# at its halts), so the walrus the ``if`` test bound before the raise was
# lost and the handler read ``a`` unbound.  The header is an expression run
# before any suite: its walrus is read at the halt through its key
# (``_compound_halt_state``, ``at_header``), as a simple statement's is.
_IF_TEST_WALRUS_RAISES = _walrus_test("        if {test}:\n            pass\n", _RAISE)


def test_the_truthful_half_reads_the_if_tests_walrus_bound_before_the_raise() -> (
    None
):
    # TRUTHFUL: Python binds ``a = 1``, then ``int("x")`` raises; the handler
    # returns 1.
    outcome = function_universe_outcome(_function(_IF_TEST_WALRUS_RAISES))
    assert _returned_value(outcome) == TermValue(1)


def test_the_lying_half_raises_name_error_for_the_if_tests_walrus() -> None:
    # LYING: every arm a ``NameError`` for ``a``, the walrus dropped at the
    # ``if``'s halt.
    from sugar_lift_py_tests.effect import NameErrorEffect

    outcome = function_universe_outcome(_function(_IF_TEST_WALRUS_RAISES))
    assert not any(
        isinstance(exit_, Halted) and isinstance(exit_.effect, NameErrorEffect)
        for exit_ in outcome.exits
    ), outcome


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
    # The message is a compared child built with the statement; a walrus in
    # it runs before ``AssertionError``, so the statement holds it, and a
    # record-less failure is refused, never given the prefix that drops the
    # bind.
    assert holds_a_walrus(AssertSugar(_One(), None, message=_walrus()))
    assert not holds_a_walrus(AssertSugar(_One(), None, message=_One()))
    assert not holds_a_walrus(AssertSugar(_One(), None))


def _built_assert(source: str) -> AssertSugar:
    from sugar_source_tree.nodes import Assert

    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (source, "every_halt_record.py", blake3_512_of(source.encode())),
        construction_context=context,
    )
    node = next(node for node in tree.nodes() if isinstance(node, Assert))
    return node.sugar()


def test_an_assert_built_from_source_holds_its_messages_walrus() -> None:
    # The message's sugar is built at construction, with the test's.
    built = _built_assert("def f():\n    assert True, (m := 'x')\n")
    assert isinstance(built.message, NamedExprSugar)
    assert holds_a_walrus(built)
    assert not holds_a_walrus(_built_assert("def f():\n    assert True, 'x'\n"))
    assert _built_assert("def f():\n    assert True\n").message is None


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


# -- an operand's halt carries every write of the operands before it ------------


@dataclass(frozen=True)
class _Display(ConstructedTermSugar):
    """``[*operands]``: its operands reduced left to right through the one
    fold a display's elements take (``reduce_operands``), then consumed by
    one step."""

    operands: tuple
    site: object = field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        from sugar_lift_py_tests.floor.named_expression_value import (
            consume_operands,
            reduce_operands,
        )

        return reduce_operands(self.operands, ctx).and_then(
            lambda values: consume_operands(
                lambda *presented: ExitSet.completed(TermValue(len(presented))),
                *values,
            )
        )

    def to_term(self, *, owner: str):
        raise NotImplementedError(owner)


def test_a_later_operands_halt_lays_an_earlier_operands_callee_store() -> None:
    # ``x = [f(o), d[k]]`` where ``f`` stores ``o.x`` and ``d[k]`` raises: the
    # store was made before the ``KeyError``. The halt used to offer no record
    # (no walrus anywhere), and the statement's prefix stood in for it,
    # dropping the store.
    statement = AssignSugar(
        "x", _Display((_carries_a_store(), _LeaksAsOperand())), None
    )
    assert _halt_entries(statement) == (TermValue(7), _STORE)


def test_a_later_operands_own_record_lays_an_earlier_operands_callee_store() -> (
    None
):
    # ``x = [f(o), g()]`` where ``g`` raises inside its body: the call's halt
    # carries its own record; ``f``'s store is laid first.
    statement = AssignSugar(
        "x", _Display((_carries_a_store(), _HaltsWhereItRuns())), None
    )
    assert _halt_entries(statement) == (TermValue(7), _STORE)


def test_an_operand_head_record_after_a_walrus_lays_the_callee_store() -> None:
    # ``x = [f(o), d[k], (a := 1)]``: the display holds a walrus, so ``d[k]``'s
    # halt is recorded at its head (``_recorded_at_its_head``), in a context
    # holding ``f``'s store. The store is in its entries too, where it used
    # to ride the context alone.
    statement = AssignSugar(
        "x", _Display((_carries_a_store(), _LeaksAsOperand(), _walrus())), None
    )
    assert _halt_entries(statement) == (TermValue(7), _STORE)


def test_an_operand_after_no_write_halts_as_it_did() -> None:
    # Nothing written before the halting operand: it is handed on with no
    # record, for its statement to record at its head.
    ctx = ReduceContext.root(owner="every-halt-record.display-free")
    (halt,) = [
        exit_
        for exit_ in _Display((_One(), _LeaksAsOperand())).desugar(ctx).exits
        if isinstance(exit_, Halted)
    ]
    assert halt.state is None


def test_an_operand_evaluated_after_a_store_is_recorded_at_its_head() -> None:
    # The one operand evaluation after earlier operands (``evaluated_after``):
    # the record-less halt is recorded where the operand was evaluated, the
    # earlier store first in its entries.
    from sugar_lift_py_tests.floor.named_expression_value import evaluated_after

    ctx = ReduceContext.root(owner="every-halt-record.evaluated-after")
    earlier = carry_caller_stores((_STORE,), TermValue(1))
    (halt,) = [
        exit_
        for exit_ in evaluated_after((earlier,), _LeaksAsOperand(), ctx).exits
        if isinstance(exit_, Halted)
    ]
    assert isinstance(halt.state, _ReducedBlock)
    assert halt.state.entries == (_STORE,)
    assert halt.state.context is ctx


def test_an_operand_inside_an_earlier_door_is_recorded_without_its_store() -> None:
    # A later actual runs inside the earlier actual's operand door, which
    # lays the store in every halt of its step: here the halt is recorded at
    # the operand's head alone, so the store is laid once.
    from sugar_lift_py_tests.floor.named_expression_value import (
        consume_operands,
        evaluated_after,
    )

    ctx = ReduceContext.root(owner="every-halt-record.inside-a-door")
    earlier = carry_caller_stores((_STORE,), TermValue(1))
    inside = evaluated_after((), _LeaksAsOperand(), ctx, inside=(earlier,))
    (halt,) = [exit_ for exit_ in inside.exits if isinstance(exit_, Halted)]
    assert halt.state.entries == ()
    door = consume_operands(lambda _presented: inside, earlier)
    (halt,) = [exit_ for exit_ in door.exits if isinstance(exit_, Halted)]
    assert halt.state.entries == (_STORE,)


def _never_finished(_values):
    raise AssertionError("every path halted before the fold finished")


def test_a_spread_operands_halt_lays_an_earlier_operands_callee_store() -> None:
    # ``[*f(o), *d[k]]``: ``f``'s store was made before ``d[k]`` raised. The
    # spread fold used to evaluate every operand in the same context, so
    # the halt offered no record and the statement's prefix stood in.
    from sugar_lift_py_tests.sugar.spread_sugar import _collect

    ctx = ReduceContext.root(owner="every-halt-record.spread-store")
    exits = _collect(
        (_carries_a_store(), _LeaksAsOperand()), ctx, (), _never_finished
    )
    (halt,) = [exit_ for exit_ in exits.exits if isinstance(exit_, Halted)]
    assert isinstance(halt.state, _ReducedBlock)
    assert halt.state.entries == (_STORE,)


def test_a_later_spread_operand_reads_an_earlier_operands_walrus() -> None:
    # ``[*(a := xs), *a]``: the second operand is evaluated where the
    # walrus left the context.
    from sugar_lift_py_tests.sugar.spread_sugar import _collect

    ctx = ReduceContext.root(owner="every-halt-record.spread-walrus")
    ran: list = []
    _collect(
        (_walrus(), _Counted(ran)),
        ctx,
        (),
        lambda values: ExitSet.completed(len(values)),
    )
    (operand_ctx,) = ran
    assert operand_ctx.temporal.value_if_bound(_WALRUS_KEY) == TermValue(1)


def test_a_spread_calls_argument_halt_lays_the_callees_store() -> None:
    # ``g(o)(*d[k])``: the callee expression ran (storing on ``o``) before
    # the starred argument raised.
    from sugar_lift_py_tests.sugar.spread_sugar import SpreadCallSugar

    ctx = ReduceContext.root(owner="every-halt-record.spread-call")
    call = SpreadCallSugar(
        callee_name=None,
        callee=_carries_a_store(),
        arguments=(("star", None, _LeaksAsOperand()),),
        site=None,
    )
    (halt,) = [exit_ for exit_ in call.desugar(ctx).exits if isinstance(exit_, Halted)]
    assert halt.state.entries == (_STORE,)


def test_operands_reduced_after_a_receiver_carry_its_writes() -> None:
    # A container call's arguments are reduced after its receiver
    # (``PathContainerCallSugar._call``: ``reduce_operands``'s ``earlier``):
    # an argument's halt lays the receiver's callee store, and an argument
    # reads the receiver's walrus.
    from sugar_lift_py_tests.floor.named_expression_value import reduce_operands

    ctx = ReduceContext.root(owner="every-halt-record.receiver-store")
    receiver = carry_caller_stores((_STORE,), TermValue(1))
    exits = reduce_operands((_LeaksAsOperand(),), ctx, earlier=(receiver,))
    (halt,) = [exit_ for exit_ in exits.exits if isinstance(exit_, Halted)]
    assert halt.state.entries == (_STORE,)

    ran: list = []
    walrus = _walrus().desugar(ctx).completed_value()
    reduce_operands((_Counted(ran),), ctx, earlier=(walrus,))
    (operand_ctx,) = ran
    assert operand_ctx.temporal.value_if_bound(_WALRUS_KEY) == TermValue(1)


# -- a Name-only unpack lays its right-hand side's callee stores -----------------

_UNPACK_KEY = EVALUATION_PREFIX + "every-halt-record.unpack"


@pytest.mark.parametrize("nested", [False, True], ids=["flat", "nested"])
def test_a_completed_unpack_lays_the_right_sides_callee_store(nested) -> None:
    # ``a, b = f(o)`` / ``(a, b), c = f(o)`` where ``f`` stores ``o.x``: the
    # completed record holds the store in its entries, where it used to ride
    # the carried value alone, and binds every member.
    from sugar_lift_py_tests.floor.tuple_literal_value import TupleLiteralValue
    from sugar_lift_py_tests.sugar.dynamic_unpack_assign_sugar import (
        DynamicUnpackAssignSugar,
    )
    from sugar_lift_py_tests.sugar.nested_dynamic_unpack_assign_sugar import (
        NestedDynamicUnpackAssignSugar,
    )
    from sugar_lift_py_tests.temporal.temporal_context import projection_key

    one, two, three = TermValue(1), TermValue(2), TermValue(3)
    if nested:
        value = TupleLiteralValue((TupleLiteralValue((one, two)), three))
        statement = NestedDynamicUnpackAssignSugar(
            (("a", "b"), "c"),
            _Presents(carry_caller_stores((_STORE,), value)),
            "site",
            evaluation=_UNPACK_KEY,
        )
    else:
        statement = DynamicUnpackAssignSugar(
            ("a", "b"),
            _Presents(carry_caller_stores((_STORE,), TupleLiteralValue((one, two)))),
            "site",
            evaluation=_UNPACK_KEY,
        )
    ctx = ReduceContext.root(owner="every-halt-record.unpack-stores")
    record = statement.desugar(ctx).completed_value()
    assert isinstance(record, _ReducedBlock)
    assert record.entries == (_STORE,)
    temporal = record.context.temporal
    assert temporal.value_if_bound(projection_key(_UNPACK_KEY, "a")) == one
    assert temporal.value_if_bound(projection_key(_UNPACK_KEY, "b")) == two


def test_a_completed_unpack_with_no_callee_store_completes_as_it_did() -> None:
    from sugar_lift_py_tests.floor.scope_rebind import ScopeRebinds
    from sugar_lift_py_tests.floor.tuple_literal_value import TupleLiteralValue
    from sugar_lift_py_tests.sugar.dynamic_unpack_assign_sugar import (
        DynamicUnpackAssignSugar,
    )

    statement = DynamicUnpackAssignSugar(
        ("a", "b"),
        _Presents(TupleLiteralValue((TermValue(1), TermValue(2)))),
        "site",
        evaluation=_UNPACK_KEY,
    )
    ctx = ReduceContext.root(owner="every-halt-record.unpack-plain")
    assert isinstance(statement.desugar(ctx).completed_value(), ScopeRebinds)


# -- a failing assert evaluates its message before it raises ---------------------


def test_a_failing_asserts_message_walrus_is_bound_when_it_raises() -> None:
    # ``assert 1 == 2, (a := 1)``: CPython runs the message before it raises
    # ``AssertionError``, so the handler reads ``a`` as it does when the
    # walrus ran in a statement of its own. The message was never reduced,
    # and the statement, holding its walrus, was refused.
    assert _returned_after(
        "        assert 1 == 2, (a := 1)\n", "AssertionError"
    ) == _returned_after("        (a := 1)\n        assert 1 == 2\n", "AssertionError")


def test_an_assert_built_from_source_holds_its_messages_yield() -> None:
    # The message is built with the statement, never during reduction: a
    # ``(yield 2)`` there is its own sugar from construction (a yield
    # expression is a suspension, ``Yield._construct_sugar``), held by the
    # assert even though the assert cannot fail.
    from sugar_lift_py_tests.sugar.yield_suspension_sugar import (
        YieldSuspensionSugar,
    )

    built = _built_assert("def f():\n    assert 1 == 1, (yield 2)\n")
    assert isinstance(built.message, YieldSuspensionSugar)


@dataclass(frozen=True)
class _Counted(Sugar):
    """An operand that records each evaluation in ``ran``."""

    ran: list = field(compare=False)
    site: object = field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        self.ran.append(ctx)
        return ExitSet.completed(TermValue(1))


def test_a_passing_asserts_message_is_never_evaluated() -> None:
    # The message is built with the statement, but evaluated only beneath
    # the assert's own failure (CPython semantics).
    from dataclasses import replace

    ctx = ReduceContext.root(owner="every-halt-record.assert-message")
    ran: list = []
    passing = replace(
        _built_assert("def f():\n    assert True, 'x'\n"), message=_Counted(ran)
    )
    assert not any(isinstance(e, Halted) for e in passing.desugar(ctx).exits)
    assert ran == []
    failing = replace(
        _built_assert("def f():\n    assert False, 'x'\n"), message=_Counted(ran)
    )
    assert any(isinstance(e, Halted) for e in failing.desugar(ctx).exits)
    assert len(ran) == 1
