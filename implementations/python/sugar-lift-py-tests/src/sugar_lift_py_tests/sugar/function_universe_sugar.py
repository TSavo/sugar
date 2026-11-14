"""A function definition, lowered to its universe.

This is the SPINE the whole tree lift stands on. `FunctionDef.sugar()` (on the
AST node) constructs one of these WITH the already-built sugars of its body
statements; `desugar` reduces that body in order into a `BlockValue` record and
wraps it in a `UniverseValue`. The universe's `invs()` are the stated facts the
body emits; its `post()` is the exit constraint `out == <term>` -- the callee
contract a caller's INV discharges against.

Meaning-only, node-constructed: no `owns`, no `new`, no catalog, no SugarBody.
The block reduction here is the factory's `_collect_iterative` (block_sugar.py)
with the one factory coupling removed -- it reduces each statement by calling
`.desugar(ctx)` directly instead of through a SugarBody wrapper. The floor
values it produces (BlockValue, UniverseValue, and every entry's
inv_contribution/post_contribution) are pure meaning and are reused verbatim.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field, replace

from sugar_lift_py_tests.floor import BlockValue
from sugar_lift_py_tests.floor.universe_value import UniverseValue
from sugar_lift_py_tests.outcome import (
    Completed,
    ExitSet,
    Halted,
    true_guard,
)
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class _ReducedBlock:
    entries: tuple[object, ...]
    can_fall_through: bool
    fall_through: tuple
    transforms: tuple = ()
    # The live reducer context the block was reduced under: a lookup aid a
    # continuation reads bindings OUT of, never testimony (it is already out of
    # equality). ``entries`` and ``fall_through`` are the block's content.
    context: object = dataclass_field(
        default=None, compare=False, repr=False, metadata={"testimony": "lookup"}
    )
    # The generator frame a halt raised inside a generator's machinery left
    # (``GeneratorConstructionV1`` at the step it halted on), carried INSIDE
    # the record the halt carries (``halt_record(..., frame=)``), never in its
    # place: a cited-opaque ``__exit__`` that suppresses the halt continues
    # that frame. Like ``context`` it is a lookup aid, never testimony, so it
    # is out of equality. ``None`` on every record a block reduced.
    frame: object = dataclass_field(
        default=None, compare=False, repr=False, metadata={"testimony": "lookup"}
    )


def _extend_receiver_store_scope(value, ctx):
    """Thread statement-owned rebinds: Floor ``extend_scope`` only.

    The reducer does not probe capability, ladder rebind kinds, or mint root
    contexts.  Default FloorValue.extend_scope is identity; Floors that rebind
    (ScopeRebind, ReceiverFieldStoreValue, …) own their own root-context mint
    when ``ctx`` is absent.  ``value`` is the completed arm's FloorValue, which
    owns ``extend_scope``.
    """
    return value.extend_scope(ctx)


def plain_completed_value(outcome):
    """The value of ONE plain completed arm, else ``None``.

    Plain: one completed arm under truth, carrying no partition faces and owing
    nothing -- the arm a total step answers. Its value may be handed on alone.
    An arm with faces or debts is sequenced instead, so the sequencing carries
    them onto every continuation (``owed`` is never dropped). A deferred
    native-operation carrier is not an ``ExitSet`` and answers ``None``. A
    set of several arms answers ``None`` before anything normalizes it.
    """
    if not isinstance(outcome, ExitSet) or len(outcome.exits) != 1:
        return None
    arm = outcome.exits[0]
    if arm.faces or arm.owed:
        return None
    return outcome.completed_value()


def _plain_halt(outcome: ExitSet):
    """The effect of ONE plain halted arm that carries no state, else ``None``.

    Plain: one halted arm under truth, no partition faces, owing nothing, and
    no temporal state of its own -- a halt at the head of a statement that
    declares it halts there and holds no walrus (``halts_at_statement_head``;
    any other statement's record-less halt is refused first,
    ``_require_recorded_halts``), whose pre-halt state is the enclosing
    block's prefix.
    """
    if len(outcome.exits) != 1:
        return None
    arm = outcome.exits[0]
    if (
        isinstance(arm, Halted)
        and arm.guard == true_guard()
        and arm.state is None
        and not arm.faces
        and not arm.owed
    ):
        return arm.effect
    return None


def _prefixed(state: _ReducedBlock, inner: _ReducedBlock) -> _ReducedBlock:
    """The temporal state of a halt INSIDE a nested statement, read from outside.

    ``inner`` is the record the nested reduction reached before halting;
    ``state`` is everything this block had already established when the
    statement began. Python never rolls back what already happened, so the
    halt arm carries both, in order. Every halt reaching here carries a
    record: the block reducer refused a record-less one at the statement
    (``_require_recorded_halts``) or gave it the prefix whole.

    Identity law (R1): when the prefix contributes nothing (no entries, no
    transforms), the nested record already IS the complete temporal state.
    Return it by object identity — do not re-seat an ``==``-equal
    ``_ReducedBlock``. Re-seating broke unmatched WithEffectBoundarySugar
    residuals (``face.state is halted.state``) while try/except ``and_exit`` and
    NeverSuppresses correctly retained ``is``.
    """
    if not state.entries and not state.transforms:
        # Empty prefix: retain the nested pre-halt record as the same cell.
        return inner
    entries = inner.entries
    for transform in reversed(state.transforms):
        entries = transform(entries)
    return _ReducedBlock(
        (*state.entries, *entries),
        inner.can_fall_through,
        (),
        state.transforms,
        inner.context,
    )


def _halt_state(state: _ReducedBlock, exit_) -> object:
    """The temporal record a halted arm of a nested statement carries.

    ``_prefixed``: the nested reduction's own record with this block's prefix
    spliced in front. Every halt a compound statement hands back carries a
    record (``halt_record``, ``halts_recorded``): one at its head, before
    anything of the statement ran, carries the empty record in the context
    it halted in, and the prefix spliced here is then its whole record.
    """
    return _prefixed(state, exit_.state)


def _require_recorded_halts(outcome, statement) -> None:
    """THE BOUNDARY between an expression's halt and a block's: stop by name
    (``SugarNotWritten``, owner ``reduce_block_to_exitset.statement``) a
    statement that hands the block reducer a halt with no record.

    A halt's state is ``None`` only inside an expression's evaluation: the
    expression offers no record of its own. The statement that runs it
    records it before the halt leaves the statement -- at its head
    (``halt_record``, ``halts_recorded``), or after what it bound first
    (``NestedDynamicUnpackAssignSugar``: the outer targets an inner unpack
    halted after). A statement that binds nothing before any of its halts
    declares so (``halts_at_statement_head``): the reducer records each such
    halt with the block's prefix, its whole pre-halt state. Any other
    statement whose halt still offers no record is refused here, never given
    the prefix (which would drop what the statement bound before it) and
    never let through record-less (a suite resuming after it would have
    nothing to resume from).

    The declaration is checked, not trusted: it holds only for a statement
    that holds no walrus (``holds_a_walrus``). A walrus binds as its operand
    completes, before a later operand or the statement's own step halts
    (``x, y = (a := 1), f()``, ``raise E((m := msg))``): such a halt's
    record is built where it halted, from the binds already made
    (``halts_at_operand_head``: every operand's evaluation,
    ``sugar_base._recorded_at_its_head``; every consumer's step, a
    statement's own step after its operands included -- a ``raise`` of a
    walrus's value, an ``assert`` whose test bound one --
    ``consume_operands``). One that still offers no record from a statement
    holding a walrus (an ``assert``'s failure after its message's walrus,
    whose value is never reduced) is refused here like any other: the
    prefix would drop the bind.
    """
    if not any(
        isinstance(exit_, Halted) and exit_.state is None for exit_ in outcome.exits
    ):
        return
    name = type(statement).__name__
    declared = getattr(statement, "halts_at_statement_head", False)
    if declared:
        from sugar_lift_py_tests.sugar.named_expr_sugar import holds_a_walrus

        if not holds_a_walrus(statement):
            return
    from sugar_source_tree.panic import SugarNotWritten

    site = getattr(statement, "site", None)
    raise SugarNotWritten(
        owner="reduce_block_to_exitset.statement",
        blame=site if site is not None else name,
        observed=(
            f"a {name} statement holding a walrus handing the block a halt "
            "with no record: the walrus may have bound before it halted"
            if declared
            else f"a {name} statement handing the block a halt with no record"
        ),
        requested=(
            "every halt that leaves a statement carries its record: the "
            "entries and the context it halted in"
        ),
        fix=(
            "record the halt at the statement (halt_record, halts_recorded) "
            "or where it halted, from the walrus binds already made "
            "(halts_at_operand_head); a statement that binds nothing before "
            "any halt and holds no walrus declares halts_at_statement_head"
        ),
    )


def halt_record(ctx, *, frame=None) -> _ReducedBlock:
    """The record a halt carries where nothing of its producer ran before
    it: no entries, in ``ctx``, the context it halted in.

    The one record constructor every halt's record starts from: the block
    composition splices what ran ahead of the halt onto it (``_prefixed``),
    a loop carries what its items did onto it (``_left_with``), and a suite
    that catches it resumes from it (``resumed``). A ``break``/``continue``
    halts with it (``LoopControlSugar``); so does a compound statement's
    head -- an ``if`` test, a loop's iterable, ``iter``, ``next`` and target
    unpack, a ``while`` test, a ``with`` manager and its enter, a ``match``
    subject, a ``match`` pattern, equality or guard, a ``class`` statement's
    bases and body (``halts_recorded``) -- since nothing of the statement
    ran before it.

    ``frame``: a halt raised inside a generator's machinery carries the
    generator frame it left inside its record
    (``GeneratorConstructionV1._left_here``), never in its place.
    """
    return _ReducedBlock((), False, (), context=ctx, frame=frame)


def require_halt_record(state, *, owner: str) -> None:
    """Stop by name (``SugarNotWritten``) a halt state that is no record.

    THE CHECK every ``Halted`` makes as it is constructed: a halt's state is
    the record it halted with (``_ReducedBlock``: its entries and the
    context it halted in), or ``None`` -- an expression's halt, which
    offers no record of its own because nothing of it ran before it, and
    which the statement that runs it records (``halts_recorded``, the block
    composition) before it leaves the statement: the block reducer refuses
    a statement whose halt still offers none (``_require_recorded_halts``),
    so ``None`` exists only inside an expression's evaluation. Any other
    state -- a bare context, a generator's machine,
    a value, any other payload -- is stopped here by name, never carried
    in place of a record: whatever else a halt must carry lives inside its
    record (a generator frame: ``halt_record(..., frame=)``).
    """
    if state is None or isinstance(state, _ReducedBlock):
        return
    from sugar_source_tree.panic import SugarNotWritten

    raise SugarNotWritten(
        owner=owner,
        blame=owner,
        observed=(
            f"a halt whose state is a {type(state).__name__}, not a block's "
            "record"
        ),
        requested=(
            "the record the halt carries: its entries and the context it "
            "halted in"
        ),
        fix=(
            "build the record at the producer (halt_record, halts_recorded, "
            "face_record); carry anything else inside it (a generator frame: "
            "halt_record(..., frame=)), never in its place"
        ),
    )


def face_record(face, *, owner: str, blame: object) -> _ReducedBlock:
    """The record a suite's face left: a completed face's value (the
    block's record), a halted face's state (the record it halted with).

    What runs after the face (a ``with``'s ``__exit__``, a suppressed halt
    continuing after the ``with``) runs where it left. A face whose record
    is no record is refused by name, never given an empty one: what the
    suite did before it is never dropped.
    """
    record = face.state if isinstance(face, Halted) else face.value
    if isinstance(record, _ReducedBlock):
        return record
    from sugar_source_tree.panic import SugarNotWritten

    raise SugarNotWritten(
        owner=owner,
        blame=blame if blame is not None else owner,
        observed=(
            f"a {type(face).__name__} face whose record is a "
            f"{type(record).__name__}, not a block's record"
        ),
        requested="the record the suite left on this face",
        fix=(
            "halt with a record at the producer (halt_record, "
            "halts_recorded); never make one up in its place"
        ),
    )


def halts_recorded(outcome, record: _ReducedBlock):
    """``outcome`` with every halted arm that offers no record of its own
    carrying ``record``: what ran before it, nothing of its own producer
    having run before it halted.

    At a compound statement's head (an ``if`` test, a loop's iterable,
    ``next`` or ``while`` test, a ``with`` manager or enter, a ``match``
    subject) that is ``halt_record(ctx)``, the empty record where it
    halted, onto which the block composition splices what ran before the
    statement. After a ``with`` body face (its ``__exit__``) it is the
    record that face left (``face_record``).

    An arm that carries its own record (a call's halt: the callee's) keeps
    it, and every arm keeps its guard, faces and ``owed``. A deferred
    native-operation carrier is handed back as it is: its halt is recorded
    by the block composition that enrolled its pre-effect state.
    """
    from dataclasses import replace as _replace

    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )

    if isinstance(outcome, NativeOperationExitCarrierV1):
        return outcome
    if not any(
        isinstance(exit_, Halted) and exit_.state is None for exit_ in outcome.exits
    ):
        return outcome
    return ExitSet(
        tuple(
            _replace(exit_, state=record)
            if isinstance(exit_, Halted) and exit_.state is None
            else exit_
            for exit_ in outcome.exits
        )
    )


def _offers_no_record(outcome) -> bool:
    """Whether ``outcome`` (an ``ExitSet``) has a halted arm with no record."""
    return isinstance(outcome, ExitSet) and any(
        isinstance(exit_, Halted) and exit_.state is None for exit_ in outcome.exits
    )


def halts_at_operand_head(outcome, operand, ctx):
    """``outcome`` -- ``operand`` evaluated in ``ctx`` -- with every halted
    arm that offers no record carrying ``halt_record(ctx)``, where
    ``operand`` holds no walrus; ``outcome`` as it is otherwise.

    An operand that holds no walrus (``holds_a_walrus``) binds nothing while
    it evaluates, so its record-less halt halted at its own head: what was
    bound before it is all of its record, and ``ctx`` -- the context it was
    evaluated in, every walrus bind of the operands before it applied
    (``written_by``) -- holds exactly that. ``x, y = (a := 1), f()``: ``f()``
    halts in a context where ``a`` is bound, and its halt carries it.

    The one place a halt's record is built from the binds already made: the
    one expression evaluation applies it to every operand
    (``sugar_base._recorded_at_its_head``), and a step that runs after its
    operands (``consume_operands``, an unpack of an evaluated right-hand
    side) applies it with ``operand`` None -- the step itself runs no
    walrus -- in the context its operands' binds wrote.

    An operand that holds a walrus may have bound it before a later part of
    it halted: its record-less halt is left as it is, never given a record
    that would drop the bind, and the statement that runs it records it or
    is refused by name (``_require_recorded_halts``). A context that holds
    no temporal (none at all) records nothing.
    """
    if (
        ctx is None
        or not hasattr(ctx, "temporal")
        or not _offers_no_record(outcome)
    ):
        return outcome
    from sugar_lift_py_tests.sugar.named_expr_sugar import holds_a_walrus

    if holds_a_walrus(operand):
        return outcome
    return halts_recorded(outcome, halt_record(ctx))


def laid_in_record(entries, outcome, *, halts_only: bool = False):
    """``outcome`` with ``entries`` first in the record of every arm: what
    ran in a statement before the part of it that made ``outcome`` -- the
    stores a callee made on objects this frame sees, carried by an
    assignment's values (``assigned_value.evaluate_assignment_values``) or
    by a statement's header (``header_applied``, ``header_record``).

    The one way a statement lays what it carried before its own record, as a
    statement alone lays the stores its call carried
    (``expr_statement_sugar.record_statement_value``): the record is what a
    ``return`` and the frame's exit hand the caller
    (``call_site_value.caller_visible_stores``) and what a suite resuming
    after a halt starts from (``resumed``).  A completed arm's record is its
    value -- a block's record (``_ReducedBlock``), a ``BlockValue``'s
    statements, a symbolic ``if``'s faces (``GuardedFaces``: before every
    face, with the condition's own testimony), a class body's
    (``class_definition_sugar._ClassBodyV1``); a halted arm's is its state.
    A halted arm with no record of its own is left as it is: its producer
    records it where it halted (``halts_recorded``) before it is laid here.
    A completed value that holds no record is refused by name, never handed
    on without what the statement carried.  ``halts_only``: lay ``entries``
    in the halted arms alone, for a statement that lays them in its completed
    record itself once it completes.  ``outcome`` itself when there is
    nothing to lay."""
    if not entries:
        return outcome
    from sugar_lift_py_tests.floor.guarded_faces import GuardedFaces
    from sugar_lift_py_tests.sugar.class_definition_sugar import _ClassBodyV1

    entries = tuple(entries)

    def lay(value):
        if isinstance(value, (_ReducedBlock, _ClassBodyV1)):
            return ExitSet.completed(
                replace(value, entries=(*entries, *value.entries))
            )
        if isinstance(value, BlockValue):
            return ExitSet.completed(
                replace(value, statements=(*entries, *value.statements))
            )
        if isinstance(value, GuardedFaces):
            return ExitSet.completed(
                replace(
                    value,
                    unconditional_entries=(*entries, *value.unconditional_entries),
                )
            )
        from sugar_source_tree.panic import SugarNotWritten

        raise SugarNotWritten(
            owner="laid_in_record",
            blame="laid_in_record",
            observed=(
                f"a statement completing with a {type(value).__name__}, which "
                "holds no record to lay the stores it carried in"
            ),
            requested=(
                "a completed record (a block's record, a BlockValue, a "
                "symbolic if's faces, a class body) for what the statement "
                "carried before it"
            ),
            fix=(
                "complete the statement with its record; never hand on a value "
                "without the stores its callees made"
            ),
        )

    if isinstance(outcome, ExitSet):
        outcome = ExitSet(
            tuple(
                replace(
                    exit_,
                    state=replace(exit_.state, entries=(*entries, *exit_.state.entries)),
                )
                if isinstance(exit_, Halted) and isinstance(exit_.state, _ReducedBlock)
                else exit_
                for exit_ in outcome.exits
            )
        )
    if halts_only:
        return outcome
    return outcome.and_then(lay)


def header_record(value, ctx):
    """``(presented, record)`` for the value of a statement's header -- an
    expression the statement evaluates before the rest of it reads what that
    expression did: an ``if`` test, a ``with`` item's manager, a ``match``
    subject, a ``raise`` operand.

    ``presented`` is the value beneath the writes the header made; ``record``
    is the record the rest of the statement continues after: its context is
    ``ctx`` with every walrus bind and every callee store the header carried
    applied by the one operand rule (``named_expression_value.written_by``),
    its entries the callee stores (``CallerStoreValue``), laid by
    ``laid_in_record``.  ``record`` is None where the header carried no
    write: the rest runs in ``ctx`` as it is."""
    from sugar_lift_py_tests.floor.named_expression_value import (
        caller_stores_of,
        peel_walrus_binds,
        written_by,
    )

    binds, presented = peel_walrus_binds(value)
    if not binds:
        return value, None
    _walrus, stores = caller_stores_of(binds)
    return presented, _ReducedBlock(
        stores, True, (), context=written_by(value, ctx)
    )


def header_applied(statement, field: str, ctx):
    """``(headed, outcome)``: THE one way a statement's header -- the sugar
    in ``statement``'s ``field``: a ``with`` item's manager, a ``match``
    subject, a ``raise`` operand -- reaches the rest of the statement.

    ``outcome`` is the header evaluated once, in ``ctx``.  Where no completed
    face of it carries a write (a walrus bind, a callee store), ``headed`` is
    None and the statement runs as it is, from ``outcome``.  Otherwise
    ``headed`` is the statement: each halted face of the header halted at
    the statement's head (``halt_record(ctx)``); on each completed face the
    statement runs again with the header fixed to the value it presents, in
    the context its writes leave (``header_record``), every halt of that
    run that offers no record recorded there, and the callee stores the
    header carried first in every record it makes (``laid_in_record``) --
    the same mechanism an operand's walrus binds reach a later operand by
    (``written_by``, ``halts_at_operand_head``), wherever the header sits.
    Each run keeps its face's guard, faces and ``owed`` (``ExitSet.sequence``)."""
    from sugar_lift_py_tests.floor.named_expression_value import (
        peel_walrus_binds,
    )
    from sugar_lift_py_tests.sugar.match_sugar import _CompleteValueSugar

    header = getattr(statement, field)
    outcome = header.desugar(ctx)
    if not isinstance(outcome, ExitSet) or not any(
        isinstance(exit_, Completed) and peel_walrus_binds(exit_.value)[0]
        for exit_ in outcome.exits
    ):
        return None, outcome
    site = getattr(statement, "site", None)

    def run(value):
        presented, record = header_record(value, ctx)
        fixed = replace(statement, **{field: _CompleteValueSugar(presented, site)})
        if record is None:
            return fixed.desugar(ctx)
        ran = halts_recorded(
            fixed.desugar(record.context),
            replace(record, entries=(), can_fall_through=False),
        )
        return laid_in_record(record.entries, ran)

    return halts_recorded(outcome, halt_record(ctx)).sequence(run), outcome


def resumed(state, ctx, *, owner: str, blame: object) -> _ReducedBlock:
    """The record a suite resumes from where a halt left: the one way every
    continuation after a halt begins -- an ``except`` handler that caught
    it, an ``except*`` handler's frontier, a ``finally`` beneath it (or
    beneath a completed face, ``TrySugar``), a ``with`` exit it reaches, a
    ``with`` that suppresses it and goes on after the statement
    (``ExitSet.and_exit``/``and_exit_truthiness``, ``resume=``), and a
    loop going on after its own ``break``/``continue``.

    A halt's record is everything the block reached before it halted --
    every store, rebind, container mutation and walrus bind, in its
    ``entries`` and in the ``context`` it halted in -- and Python never
    rolls any of it back. So the suite continues after that record exactly
    as a block continues after a statement (``reduce_block_to_exitset``,
    ``after=``): it reads what the record's context binds and its own
    entries follow the record's. The record goes on: the halt's own
    fall-through flag is about the block that halted, not the suite that
    resumes, and the guard of every ``return`` before the halt is already
    on the halt's arm (the reducer guards everything after a ``return`` by
    its fall-through), so it is not stated again -- neither as a
    fall-through guard nor as the transform that would guard every entry
    the suite adds. A ``finally`` beneath a completed face runs on every
    path through it, a ``return`` taken under a guard included, so it too
    resumes unguarded; the face's own guards go back on when its exit is
    re-emitted (``TrySugar``). A record reduced with no context (a nested
    record its producer built bare) reads ``ctx``.

    The record's ``return`` entries (``_is_return_entry``) are dropped: none
    is live on the halt's arm. A ``return`` reached under a guard before the
    halt is one the halt's arm excludes (the reducer guards the halt by the
    fall-through, and the ``return`` leaves as its own completed face beside
    it, ``_prior_return_face``, where it stays); a ``return`` the halt
    superseded (a raise in a ``with``'s ``__exit__`` after the body
    returned) Python discarded when the halt was raised. So what resumes
    never carries them: its own ``return`` never stands beside them, and
    nothing re-emits them after it. A completed face's ``return`` entries
    are pending, not dead: a ``finally`` beneath it sets them aside before
    it resumes (``try_sugar._pending_returns``) and re-emits them after.

    Every halt carries a record (``halt_record``): its producer builds it.
    A halt whose state is no record -- ``None``, a bare context, any other
    payload -- holds nothing to resume from, and an empty record made up in
    its place would drop what ran before the halt: it is refused by name,
    never given one.
    """
    if isinstance(state, _ReducedBlock):
        return replace(
            state,
            entries=tuple(
                entry for entry in state.entries if not _is_return_entry(entry)
            ),
            can_fall_through=True,
            fall_through=(),
            transforms=(),
            context=state.context if state.context is not None else ctx,
        )
    from sugar_source_tree.panic import SugarNotWritten

    raise SugarNotWritten(
        owner=owner,
        blame=blame if blame is not None else owner,
        observed=(
            f"a halt whose state is a {type(state).__name__}, not a block's "
            "record"
        ),
        requested=(
            "the halt's record (its entries and the context it halted in), "
            "to resume the suite after"
        ),
        fix=(
            "halt with a record at the producer (halt_record, "
            "halts_recorded); never resume a suite from a record made up "
            "in place of the halt's"
        ),
    )


def _is_return_entry(entry) -> bool:
    """A record entry that is a ``return`` (guarded by its arm or not)."""
    from sugar_lift_py_tests.floor.guarded_return import GuardedReturn
    from sugar_lift_py_tests.floor.return_value import ReturnValue

    return isinstance(entry, (GuardedReturn, ReturnValue))


def _prior_return_face(state, ctx) -> "ExitSet | None":
    """The completed exit an earlier guarded ``return`` already took.

    After ``if c: return v`` the block goes on only under the fall-through
    guard.  A later statement that halts, or that reduces to its own exits,
    is guarded by it.  Where that guard fails, the function already returned,
    and that completed exit, with its tail unreachable, must stay beside the
    later statement's faces.  Dropping it made ``if c: return 7`` followed by
    ``raise`` claim the function always raised.

    ``None`` when no earlier ``return`` fired; otherwise the one completed
    arm (``ExitSet.completed``) that joins the later statement's faces.
    """
    if not state.fall_through or not any(
        _is_return_entry(entry) for entry in state.entries
    ):
        return None
    from sugar_lift_py_tests.outcome.exit_set import complement_guard

    return ExitSet.completed(
        _ReducedBlock(state.entries, False, (), state.transforms, ctx),
        complement_guard(_fall_through_guard(state)),
    )


def _fall_through_guard(state):
    """The guard under which ``state``'s block goes on past its earlier
    guarded ``return``s: the conjunction of its fall-through guards."""
    from sugar_lift_py_tests.ir import and_

    return (
        state.fall_through[0]
        if len(state.fall_through) == 1
        else and_(list(state.fall_through))
    )


def past_prior_returns(state, ctx, goes_on, returned):
    """What follows a completed record ``state`` that falls through, where
    what follows is not a statement of the same block (a loop's next item,
    or the loop's exit after its item): the one composition a block gives a
    statement after a guarded ``return``.

    With no earlier ``return`` taken (``_prior_return_face`` is ``None``) it
    is ``goes_on(state)``. Otherwise ``state`` is split where the block
    reducer splits a later statement: the earlier ``return``'s completed face
    (``_prior_return_face``) leaves by ``returned(record)``, under the
    complement of the fall-through guard; and what follows runs by
    ``goes_on(record)`` under the fall-through guard
    (``_fall_through_guard``), from the record without its ``return``
    entries, fall-through guard and transforms -- the arm's guard already
    says no earlier ``return`` was taken, so none of them is live on it (as
    ``resumed`` drops them after a halt), and what follows never stands
    beside them. One composition beneath both (``ExitSet.sequence``), which
    hands on a continuation still waiting on its caller's actuals.
    """
    earlier = _prior_return_face(state, ctx)
    if earlier is None:
        return goes_on(state)
    live = replace(
        state,
        entries=tuple(
            entry for entry in state.entries if not _is_return_entry(entry)
        ),
        fall_through=(),
        transforms=(),
    )
    branches = ExitSet((Completed(_fall_through_guard(state), live), *earlier.exits))

    def after(record):
        if record.can_fall_through:
            return goes_on(record)
        return returned(record)

    return branches.sequence(after)


def reduce_block_to_exitset(
    statements: tuple, ctx: object = None, *, after: object = None
) -> ExitSet[_ReducedBlock]:
    """Reduce a suite to guarded exits before the linear compatibility view.

    ``after`` is the record the suite continues after (an ``else`` after the
    ``try`` body's completion, a handler or ``finally`` after the record a
    halt carries: ``resumed``): the suite's first statement reduces where
    that record left off, as every statement reduces where the one before it
    left off, and its entries follow the record's. Without it the suite
    begins from nothing, under ``ctx``.
    """
    if ctx is None:
        from sugar_lift_py_tests.context import ReduceContext

        ctx = ReduceContext.root(owner="reduce_block_to_exitset")
    if after is None:
        after = _ReducedBlock(
            entries=(), can_fall_through=True, fall_through=(), context=ctx
        )
    elif not isinstance(after, _ReducedBlock):
        from sugar_source_tree.panic import SugarNotWritten

        sites = [getattr(statement, "site", None) for statement in statements]
        raise SugarNotWritten(
            owner="reduce_block_to_exitset.after",
            blame=next(
                (site for site in sites if site is not None),
                "reduce_block_to_exitset.after",
            ),
            observed=f"a suite continuing after a {type(after).__name__}",
            requested="the block record the suite continues after",
            fix="continue a suite after a block's record, never another value",
        )
    exits = ExitSet.completed(after)

    for index, head in enumerate(statements):

        def reduce_next(
            state: _ReducedBlock, *, statement=head
        ) -> ExitSet[_ReducedBlock]:
            # A native-operation carrier may retain this callback until after
            # the outer reducer loop advances. Bind the current statement now;
            # a late-bound ``head`` skips the deferred tail to the final node.
            if not state.can_fall_through:
                # A terminal Completed face (return, including return from
                # finally) owns the exit.  It is completed rather than halted,
                # but its source tail is unreachable and must not be reduced
                # into a contradictory second post-state.
                return ExitSet.completed(state)
            active_ctx = state.context if state.context is not None else ctx
            statement_ctx = active_ctx
            # ObservedEffectBinding rows are producer testimony for a consumed
            # slot (Try/With routing). Thread them into the next statement's
            # reduction context so EffectRef / ObservationRef project the same
            # RaiseEffect the boundary routed — not a pure unauthenticated
            # coordinate. Handler bodies also receive this via
            # TrySugar.with_observed_effect before their first statement.
            from sugar_lift_py_tests.effect_router import ObservedEffectBinding

            observed = tuple(
                entry
                for entry in state.entries
                if isinstance(entry, ObservedEffectBinding)
            )
            if observed:
                from sugar_lift_py_tests.context import ReduceContext

                statement_ctx = (
                    ReduceContext.root(owner="reduce_block_to_exitset")
                    if statement_ctx is None
                    else ReduceContext.derived(
                        statement_ctx, owner="reduce_block_to_exitset"
                    )
                )
                for binding in observed:
                    statement_ctx = statement_ctx.with_observed_effect(
                        binding.slot_id, binding.effect
                    )
            outcome = statement.desugar(statement_ctx)

            def project(value):
                if isinstance(value, _ReducedBlock):
                    contribution = value.entries
                    continues = value.can_fall_through
                    nested_fall_through = value.fall_through
                    nested_transforms = value.transforms
                    next_context = (
                        value.context if value.context is not None else active_ctx
                    )
                else:
                    # The value owns its contribution, its follow and its scope.
                    contribution = value.contribution()
                    follow = value.follow_rest()
                    continues = follow.continues
                    nested_fall_through = (
                        ()
                        if follow.continuation_guard is None
                        else (follow.continuation_guard,)
                    )
                    nested_transforms = (
                        () if follow.transform is None else (follow.transform,)
                    )
                    next_context = _extend_receiver_store_scope(value, active_ctx)
                for transform in reversed(state.transforms):
                    contribution = transform(contribution)
                entries = (*state.entries, *contribution)
                if not continues:
                    return ExitSet.completed(
                        _ReducedBlock(entries, False, (), context=next_context)
                    )
                return ExitSet.completed(
                    _ReducedBlock(
                        entries,
                        True,
                        (*state.fall_through, *nested_fall_through),
                        (*state.transforms, *nested_transforms),
                        next_context,
                    )
                )

            from sugar_lift_py_tests.caller_parameter_contract import (
                NativeOperationExitCarrierV1,
                ReducerPreEffectStateV1,
            )

            if isinstance(outcome, NativeOperationExitCarrierV1):
                # A formal native operation is neither a completion nor a halt
                # until an authenticated caller supplies its actual operands.
                # Retain the ordinary statement projection as a continuation;
                # discharge will feed its Completed face through this exact
                # block seam, while its Halted face bypasses the tail.
                # Enroll this block's reducer state only once. A callee that
                # already enrolled at the lookup (stringify_exception at
                # exc.message) keeps that inner state; this caller omits a
                # second conflicting enrollment and only appends project.
                if outcome.pre_effect_state is not None:
                    return outcome.and_then(project)
                return outcome.and_then(
                    project,
                    pre_effect_state=ReducerPreEffectStateV1._from_reducer(state),
                )

            plain = plain_completed_value(outcome)
            if plain is not None and not isinstance(plain, _ReducedBlock):
                # One plain completion: the statement's value carries the block
                # straight on. The value owns its contribution, its follow and
                # its scope (``project``); the fall-through guard stays in the
                # record, where every earlier statement left it. A store is not
                # split here: its producer answers its two faces
                # (``store_faces``), and they arrive through the seam below.
                return project(plain)

            # The boundary: a halt leaves a statement with its record, or
            # from the head of a statement that declares it binds nothing
            # before any halt. ``None`` lives only inside an expression.
            _require_recorded_halts(outcome, statement)

            effect = _plain_halt(outcome)
            if effect is not None:
                # One plain halt at the statement: nothing ran inside it before
                # the halt, so its pre-halt state is this block's prefix.
                halted = ExitSet.halted(effect, state=state)
                returned = _prior_return_face(state, active_ctx)
                if returned is not None:
                    # Reached only where no earlier ``return`` fired.
                    return halted.guarded(_fall_through_guard(state)).union(returned)
                return halted

            returned = _prior_return_face(state, active_ctx)
            if state.fall_through:
                outcome = outcome.guarded(_fall_through_guard(state))

            # A statement that reduces to its OWN ExitSet (a nested block:
            # try/with, or an unpack assignment whose store leaves are
            # sequenced by this same reducer) hands back halted arms whose
            # state is the state reached INSIDE that statement. It cannot
            # know the prefix -- `head.desugar(ctx)` is given no state -- so
            # the prefix is spliced on here, at the one seam that owns
            # sequencing. Without this, a halt inside a nested statement
            # would report an empty temporal state and every earlier store
            # would read as rolled back (Python never rolls back a store).

            def spliced(halt):
                # The halt leaves from the prefix spliced onto its own state;
                # ``sequence`` keeps its guard, faces and ``owed``. A
                # record-less arm reaches here only from a statement that
                # binds nothing before its own halt (``halts_at_statement_head``
                # and no walrus, checked above: an expression halt, a store's
                # halted face): it halted at the head, where the prefix is the
                # whole record -- the same state the plain halt above gives.
                return ExitSet.halted(
                    halt.effect,
                    state=(
                        state if halt.state is None else _halt_state(state, halt)
                    ),
                )

            composed = outcome.sequence(project, consume=spliced)
            if returned is not None:
                return _beside_prior_returns(composed, returned)
            return composed

        from sugar_lift_py_tests.caller_parameter_contract import (
            NativeOperationExitCarrierV1,
        )

        if isinstance(exits, NativeOperationExitCarrierV1):
            exits = exits.and_then(reduce_next)
        elif (
            len(exits.exits) == 1
            and isinstance(exits.exits[0], Completed)
            and exits.exits[0].guard == true_guard()
            and not exits.exits[0].faces
            # Handing the value alone to the next statement would drop what
            # the arm owes; an owing arm sequences like any other.
            and not exits.exits[0].owed
        ):
            # The straight-line singleton is the only ExitSet face that can
            # become a deferred native-operation carrier without needing a
            # guarded carrier algebra. Preserve it directly. Branching paths
            # continue through ExitSet.sequence and remain loud if they try to
            # smuggle an undischarged carrier through a guard.
            exits = reduce_next(exits.exits[0].value)
        else:
            # A completed prefix may expose a deferred native operation.
            # ``sequence`` keeps that carrier outside ExitSet until caller
            # actuals discharge it; no ExitSet ever holds a carrier as an arm.
            exits = exits.sequence(reduce_next)

    # The block boundary is where an obligation stops being in flight, so it is
    # the one door that consumes the carriers. Doing it here rather than per
    # statement keeps a single owner and lets `sequence` compose obligations
    # across statements first.
    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )

    if isinstance(exits, NativeOperationExitCarrierV1):
        return exits
    # No completed record holds a halt (#7826): every halt is already a halted
    # arm, so there is nothing to promote out of a record here.
    return exits


def _beside_prior_returns(composed, returned: ExitSet):
    """``composed`` with the faces of every earlier ``return`` beside it.

    ``composed`` is what ``ExitSet.sequence`` answered for a statement. A
    continuation still waiting on its caller's actuals keeps waiting: the
    returned faces join its exits once it discharges (``after_discharge``);
    no arm is read off an undischarged carrier.
    """
    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )
    from sugar_lift_py_tests.outcome.exit_set import _require_exit_set

    def beside(continued):
        exits = _require_exit_set(
            continued, owner="reduce_block_to_exitset.prior-returns"
        )
        return exits.union(returned)

    if isinstance(composed, NativeOperationExitCarrierV1):
        return composed.after_discharge(beside)
    return beside(composed)


def reduce_body(statements: tuple, ctx: object = None):
    """Reduce a function body to ONE ``ExitSet`` of the body's exits.

    Every completed arm becomes `BlockValue(record)` -- the record carries
    every entry the arm reached. Every halted arm is kept as it is, with its
    guard, its pre-halt state and what it owes: the caller wraps via
    `.and_then`, so a halt never becomes a false universe.
    """
    return block_values(reduce_block_to_exitset(statements, ctx))


def block_values(exits):
    """``exits`` (a suite's ``reduce_block_to_exitset``) as ``reduce_body``
    answers it: every completed record a ``BlockValue``, every halt kept."""
    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )

    def block_value(state):
        return ExitSet.completed(
            BlockValue(
                state.entries,
                fall_through=state.fall_through,
                can_fall_through=state.can_fall_through,
            )
        )

    if isinstance(exits, NativeOperationExitCarrierV1):
        return exits.and_then(block_value)
    return exits.sequence(block_value)


@dataclass(frozen=True)
class FunctionUniverseSugar(Sugar):
    """`def <name>(<formals>): <body>` -> the body's universe.

    Constructed by `FunctionDef.sugar()` with the body statements ALREADY
    reduced to their own sugars (child-before-parent). `desugar` reduces the
    block and wraps it; the universe projects invs/post off the record.
    """

    name: str
    formals: tuple[str, ...]
    statements: tuple  # the body statements' sugars, in source order
    site: object = dataclass_field(compare=False, default=None)
    bridge_source_symbol: str | None = None
    substitution_trace: object | None = dataclass_field(compare=False, default=None)
    formal_coordinates: tuple = ()

    @classmethod
    def witnesses(cls):
        # A function whose body returns its argument; the caller asserts the
        # returned value. The truthful twin's universe post (out == z) discharges
        # the assert; the lying twin's asserted value contradicts it.
        prefix = "def A(z):\n    return z\n\n"
        return _call_pair(
            name="function_universe",
            owner_sugar="FunctionUniverseSugar",
            truthful=prefix + "def test_a():\n    assert A(2) == 2\n",
            lying=prefix + "def test_a():\n    assert A(2) == 3\n",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        # The body was already SUBSTITUTED (FunctionDef.sugar): ordinary
        # formals stay free Vars; as-bindings are EffectRef/ObservationRef
        # coordinates.  A class-owned initializer additionally carries one
        # ConstructedReceiverRef coordinate, and its enumeration entrance seats
        # that exact receiver in ``ctx``.  Threading the producer-owned context
        # here lets the existing block reducer resolve it; callers without such
        # authority continue to pass ``None`` and retain the ordinary behavior.
        return reduce_body(self.statements, ctx).and_then(
            lambda record: ExitSet.completed(
                UniverseValue(
                    name=self.name,
                    formals=self.formals,
                    record=record,
                    bridge_source_symbol=self.bridge_source_symbol,
                    formal_coordinates=self.formal_coordinates,
                )
            )
        )

    def context_manager_edges(self) -> tuple:
        """Project already-constructed CM edges without re-entering the tree."""
        from dataclasses import fields, is_dataclass

        edges = []
        stack = list(reversed(self.statements))
        seen = set()
        while stack:
            sugar = stack.pop()
            marker = id(sugar)
            if marker in seen:
                continue
            seen.add(marker)
            edge = getattr(sugar, "context_manager_edge", None)
            if edge is not None:
                edges.append(edge)
            if not is_dataclass(sugar):
                continue
            for field in reversed(fields(sugar)):
                if field.name in {
                    "site",
                    "contract_ref",
                    "context_manager_edge",
                }:
                    continue
                value = getattr(sugar, field.name)
                if isinstance(value, Sugar):
                    stack.append(value)
                elif isinstance(value, tuple):
                    stack.extend(
                        reversed(
                            tuple(item for item in value if isinstance(item, Sugar))
                        )
                    )
        return tuple(edges)
