"""`try` effect routing + finally over ExitSet.

Foundational path (not the lossy linear adapter):

    body -> guarded ExitSet -> handler routing over Halted -> finally over every exit

except-as is tree-rewritten to EffectRef(slot); matching Halted exits emit
EffectBinding facts. finally runs on every exit:

- cleanup fall-through restores the incoming exit
- cleanup halt supersedes
- cleanup terminal completion (return) supersedes
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field, replace

from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class TrySugar(Sugar):
    """handlers: ((authenticated type Sugar|None, body_sugars, slot_id), ...)"""

    body: tuple
    handlers: tuple
    orelse: tuple = ()
    finalbody: tuple = ()
    site: object = dataclass_field(compare=False, default=None)
    #: ``try-route`` address when the source tree joined a binding over this
    #: try's routes (``Try._merge_completion_nets``); ``None`` when no binding
    #: depends on the route, so no slot is confirmed.
    route_site: object = None
    #: ``((slot id, occurrence keys), ...)``: one ``try-edge`` slot per body
    #: statement a handler's or ``finally``'s joined state reads
    #: (``Try._incoming_halt_state``).  A routed halt grounds them from its
    #: own occurrence (``_ground_edges``).
    edge_keys: tuple = ()
    #: ``finally`` substituted under the state a halt carries into it
    #: (``Try.substitute``); None when that is the completion state.
    finalbody_halted: object = None

    @classmethod
    def witnesses(cls):
        prefix = (
            "def A(z):\n"
            "    try:\n"
            "        raise ValueError\n"
            "    except ValueError:\n"
            "        pass\n"
            "    return z\n\n"
        )
        return _call_pair(
            name="try_matching_except_consumes",
            owner_sugar="TrySugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(5) == 6\n",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        from sugar_lift_py_tests.caller_parameter_contract import (
            NativeOperationExitCarrierV1,
        )
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            reduce_block_to_exitset,
        )

        body_es = reduce_block_to_exitset(self.body, ctx)
        if isinstance(body_es, NativeOperationExitCarrierV1):
            return body_es.after_discharge(
                lambda discharged: self._route_discharged_body(discharged, ctx)
            )
        return self._route_discharged_body(body_es, ctx)

    def _route_discharged_body(self, body_es, ctx):
        """Route one concrete body ExitSet; carriers enter only after discharge."""
        arm_effects: list = []
        pre_finally = _route_handlers_over_exits(
            body_es,
            self.handlers,
            self.orelse,
            site=self.site,
            ctx=ctx,
            route_site=self.route_site,
            edge_keys=self.edge_keys,
            arm_effects=arm_effects,
        )

        if not self.finalbody:
            return _try_outcome(pre_finally)

        after = _and_finally_with_raise_context(
            pre_finally,
            self.finalbody,
            ctx=ctx,
            site=self.site,
            edge_keys=self.edge_keys,
            body_effects=_body_halt_effects(body_es) if self.edge_keys else (),
            arm_effects=tuple(arm_effects),
            finalbody_halted=self.finalbody_halted,
        )
        return _try_outcome(after)


def _try_outcome(exits):
    """The try's own faces, never a flattening that merges its routes.

    Every face is a route the try owns: each routed outcome keeps its own
    temporal record (stores, receiver scope, fall-through), and the block
    reducer sequences the tail under each completed face.  Flattening merged
    every completed route into one record whose entries were merely guarded,
    and put a halt inside a completed record (#7826).
    """
    return exits.normalize()


def _finally_restores(value: object) -> bool:
    """Ordinary finally fall-through restores; return-in-finally does not."""
    from sugar_lift_py_tests.floor.return_value import ReturnValue
    from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock

    if isinstance(value, _ReducedBlock):
        if not value.can_fall_through:
            return False
        if any(isinstance(e, ReturnValue) for e in value.entries):
            return False
        return True
    return True


def _occurrence_key(effect):
    occurrence = getattr(effect, "occurrence", None)
    value = getattr(occurrence, "value", occurrence)
    return value if isinstance(value, str) else None


def _body_halt_effects(body_es) -> tuple:
    from sugar_lift_py_tests.outcome.exit_set import Halted

    return tuple(
        exit_.effect for exit_ in body_es.exits if isinstance(exit_, Halted)
    )


def _ground_edges(ctx, edge_keys, effect):
    """A context in which the ``try-edge`` slots say which body statement raised
    ``effect`` (``None``: the halt did not come from the body -- every edge
    false).  A body halt whose occurrence no edge statement holds (it was raised
    inside a callee) leaves them undecided."""
    if not edge_keys or ctx is None:
        return ctx
    table = getattr(ctx, "ground_branch_results", None)
    if not isinstance(table, dict):
        return ctx
    from dataclasses import is_dataclass, replace

    if not is_dataclass(ctx):
        return ctx
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
        FalseBoolLiteralSugar,
    )
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
        TrueBoolLiteralSugar,
    )

    if effect is None:
        hit = None
    else:
        key = _occurrence_key(effect)
        if key is not None and "@" in key:
            # An occurrence path (an unrolled iteration, a callee frame)
            # qualifies the site; the site is what a body statement holds.
            key = key.split("@", 1)[0]
        hits = [slot for slot, keys in edge_keys if key is not None and key in keys]
        if len(hits) != 1:
            return ctx
        (hit,) = hits
    decided = {
        slot: (
            TrueBoolLiteralSugar(site=None)
            if slot == hit
            else FalseBoolLiteralSugar(site=None)
        )
        for slot, _keys in edge_keys
    }
    return replace(ctx, ground_branch_results={**table, **decided})


def _and_finally_with_raise_context(
    pre_finally,
    finalbody,
    *,
    ctx,
    site,
    edge_keys=(),
    body_effects=(),
    arm_effects=(),
    finalbody_halted=None,
):
    """try/finally over ExitSet, retaining body raise as implicit context.

    The ``ExitSet.and_finally`` laws (restore / cleanup-halt supersede /
    terminal cleanup supersede), composed through ``ExitSet.sequence``: the
    ``finally`` runs beneath every completed arm (``step``) and beneath every
    halted arm (``consume`` -- the try owns every halt that reaches its
    ``finally``), so each outgoing arm carries the incoming arm's guard, faces
    and ``owed`` conjoined with the cleanup arm's. A halt that a restoring
    ``finally`` lets through owes what the body owed AND what the ``finally``
    owed. When a finally raise supersedes an incoming RaiseEffect halt, attach
    that halt as ``context_effect`` on the cleanup raise if it has none —
    Python's implicit ``__context__`` for a raise in finally after a body
    exception.

    For halted incoming faces, finally is reduced under
    ``bind_in_flight_effect`` so bare re-raise / context-sensitive raises in
    finally can resolve the authentic body effect when they carry a slot.
    """
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
    from sugar_lift_py_tests.in_flight_effect import bind_in_flight_effect
    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        reduce_block_to_exitset,
    )

    # Shared fall-through cleanup (no body exception active): no body halt
    # edge reached ``finally``.
    neutral_cleanup = reduce_block_to_exitset(
        finalbody, _ground_edges(ctx, edge_keys, None)
    )
    # Slot for bind/resolve when reducing finally over a body halt.
    from sugar_lift_py_tests.occurrence import site_coordinate_cid

    finally_slot = f"try-finally-in-flight:{site_coordinate_cid(site)}"

    def after_completion(value):
        return _finally_beneath(neutral_cleanup, None, ExitSet.completed(value))

    def after_halt(halt):
        if isinstance(halt.effect, RaiseEffect):
            # Only a body halt that left untouched by every arm says which
            # body statement raised; a halt an arm raised (or re-raised) after
            # its own stores leaves the edges undecided.
            edge_ctx = (
                _ground_edges(ctx, edge_keys, halt.effect)
                if any(halt.effect is effect for effect in body_effects)
                and not any(halt.effect is effect for effect in arm_effects)
                else ctx
            )
            finally_ctx = bind_in_flight_effect(
                edge_ctx, finally_slot, halt.effect, blame=site
            )
            cleanup_es = reduce_block_to_exitset(
                finalbody if finalbody_halted is None else finalbody_halted,
                finally_ctx,
            )
        else:
            cleanup_es = neutral_cleanup
        return _finally_beneath(
            cleanup_es, halt.effect, ExitSet.halted(halt.effect, state=halt.state)
        )

    return pre_finally.sequence(after_completion, consume=after_halt)


def _finally_beneath(cleanup_es, in_flight, restored):
    """The ``finally``'s arms as the continuation beneath one incoming arm.

    Composed through ``ExitSet.sequence``: what follows each cleanup arm runs
    beneath it, so it keeps that arm's guard, faces and ``owed``, and the
    outer ``sequence`` conjoins the incoming arm's onto them. A restoring
    completion is followed by the incoming destination (``restored``, the
    incoming arm's own value or halt), a terminal completion (return in
    finally) supersedes with its own value, and a cleanup halt supersedes
    (``consume=``, with the in-flight body raise as its implicit context).
    """
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
    from sugar_lift_py_tests.outcome.exit_set import ExitSet

    def after_cleanup(value):
        if _finally_restores(value):
            return restored
        return ExitSet.completed(value)

    def supersede(clean):
        effect = clean.effect
        # Supersede: cleanup halt wins; retain body raise as context.
        if (
            isinstance(effect, RaiseEffect)
            and effect.context_effect is None
            and isinstance(in_flight, RaiseEffect)
            and effect is not in_flight
        ):
            return ExitSet.halted(
                replace(effect, context_effect=in_flight), state=clean.state
            )
        return None

    return cleanup_es.sequence(after_cleanup, consume=supersede)


def _effect_match_verdict(effect, matcher, ctx=None, *, site=None):
    """Bare except matches any raise; typed arms use the ONE matcher.

    LAW OF ONE: tree shadows → sugar → meaning. Settled match/miss meaning is
    only ``matches_raise_effect`` in ``authenticated_exception_matching``
    (authenticated operands in, ``MatchDecided`` / ``MatchRetained`` out).
    This function does not decide miss. It either:

    - refuses with ``SugarNotWritten`` when the effect kind is not what ordinary
      except sugar reads (``GroupedRaiseEffect`` is a sibling of ``RaiseEffect``,
      not a subclass — same membrane as ``TryStarSugar``), or when the handler
      type did not construct; or
    - returns the one matcher's verdict for typed arms; or
    - returns ``MatchDecided(True)`` for bare except over a real ``RaiseEffect``
      (written bare-except sugar — no type operand to match).

    Minting ``MatchDecided(False)`` here would be a second mechanism: ad-hoc
    Python fabricating a miss outside the tree→sugar path.

    Returns ``(verdict, owed)``: ``owed`` is what reading the arm's type owes
    (``ExitSet.owed_items`` of its one completed arm; the undecided citation
    of a class a star import may bind owes the ``undecided`` member).  Python
    reads the type whenever a raise reaches the arm, matched or not, so the
    router carries it beneath every face that passed the arm.
    """
    from sugar_lift_py_tests.effect.raise_effect import (
        RaiseEffect,
        UndeterminedRaiseEffect,
    )
    from sugar_lift_py_tests.authenticated_exception_matching import (
        MatchDecided,
        matches_raise_effect,
    )
    from sugar_source_tree.panic import SugarNotWritten

    # An ``UndeterminedRaiseEffect`` is an ordinary (non-group) exception
    # whose class nobody testified to. Ordinary ``except`` reads it like any
    # other leaf raise: the one matcher states the type test over the raised
    # exception value it carries (``exception_value``), so no class is
    # invented and no arm is decided by its absence.
    if not isinstance(effect, (RaiseEffect, UndeterminedRaiseEffect)):
        blame = getattr(effect, "occurrence_id", None) or site
        raise SugarNotWritten(
            blame=blame,
            owner="TrySugar._effect_match_verdict",
            observed=type(effect).__name__,
            requested="RaiseEffect for ordinary except routing",
            fix="keep ordinary except and except* distinct",
        )
    if matcher is None:
        return MatchDecided(True), ()
    from sugar_lift_py_tests.outcome.exit_set import _require_exit_set

    # The handler's matcher is read here, not retained: a deferred carrier is
    # refused by name.
    read = _require_exit_set(matcher.desugar(ctx), owner="TrySugar.handler-matcher")
    expected = read.completed_value()
    if expected is None:
        raise SugarNotWritten(
            blame=effect.occurrence_id,
            owner="TrySugar._effect_matches",
            observed="except type did not construct a completed type operand",
            requested="an authenticated exception-type value",
            fix="keep unresolved handler types loud",
        )
    return matches_raise_effect(effect, expected), read.owed_items()


def _beneath_type_read(exits, owed: tuple):
    """``exits`` continued beneath an arm type's read that owes ``owed``.

    The one composition of a continuation beneath an arm
    (``ExitSet.sequence``): the read's debt rides onto every exit, halts
    included.  A read that owes nothing leaves ``exits`` as they are."""
    from sugar_lift_py_tests.outcome.exit_set import ExitSet

    if not owed:
        return exits
    return ExitSet.completed(None, owed=owed).sequence(lambda _read: exits)


def _binding_facts_for(slot_id, effect, site) -> tuple:
    if slot_id is None:
        return ()
    from sugar_lift_py_tests.effect_router import EffectBinding

    binding = EffectBinding(
        slot_id=slot_id,
        kind="raise",
        type_name=getattr(effect, "exception_name", None),
        effect=effect,
    )
    return binding.to_facts(site=site)


def _route_confirmation(route_site, handler_count, arm, site):
    """The facts one routed outcome states about the route slots of a try
    (or of a match: ``MatchSugar``, whose arms are its cases).

    Handler ``arm`` ran: its slot is true and every other handler's is false.
    The body route (``arm is None``): every handler slot is false.  Each fact
    rides inside the routed outcome, so the outcome's own guard guards it --
    the slot is confirmed exactly where that route was taken."""
    if route_site is None:
        return ()
    from sugar_lift_py_tests.floor.branch_result_coordinate import (
        BranchResultAuthentication,
    )
    from sugar_lift_py_tests.outcome.exit_set import false_guard, true_guard
    from sugar_source_tree.binding_state import route_slot

    return tuple(
        BranchResultAuthentication(
            route_slot(route_site, index),
            true_guard() if index == arm else false_guard(),
            site,
        )
        for index in range(handler_count)
    )


def _ground_route_on_faces(exits, route_site, handler_count, arm, site):
    """Decide the route slots (a try's, or a match's) on each completed face
    of ONE route.

    A face that left the try by handler ``arm`` (or by the body, ``arm is
    None``) knows which route it took: the code after the try, reduced under
    that face, reads the joined binding as that route's own value.  The
    decision rides on the face's own reduction context -- a copy of the
    ground table -- so no other route's face sees it."""
    from dataclasses import replace

    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
        FalseBoolLiteralSugar,
    )
    from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
        TrueBoolLiteralSugar,
    )
    from sugar_source_tree.binding_state import route_slot

    decided = {
        route_slot(route_site, index).slot_id: (
            TrueBoolLiteralSugar(site=site)
            if index == arm
            else FalseBoolLiteralSugar(site=site)
        )
        for index in range(handler_count)
    }

    def decide(state):
        # The face continues as itself with the route decided in its record;
        # ``sequence`` keeps its guard, faces and ``owed``. Halts bypass.
        context = getattr(state, "context", None)
        table = getattr(context, "ground_branch_results", None)
        if isinstance(state, _ReducedBlock) and isinstance(table, dict):
            state = replace(
                state,
                context=replace(context, ground_branch_results={**table, **decided}),
            )
        return ExitSet.completed(state)

    return exits.sequence(decide)


def _ground_decided_route(routed, route_site, handler_count, ctx, site):
    """Ground the route slots when every completed outcome took one route.

    Code after the try runs only on a completed outcome, so when all of them
    came by the same route that route is decided for the continuation -- the
    joined binding collapses to that route's value, as a ground ``if`` does."""
    if route_site is None or ctx is None:
        return
    table = getattr(ctx, "ground_branch_results", None)
    if not isinstance(table, dict):
        return
    arms = {arm for arm, _exits in routed if _exits_can_complete(_exits)}
    if len(arms) != 1:
        return
    (arm,) = arms
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
        FalseBoolLiteralSugar,
    )
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
        TrueBoolLiteralSugar,
    )
    from sugar_source_tree.binding_state import route_slot

    for index in range(handler_count):
        table[route_slot(route_site, index).slot_id] = (
            TrueBoolLiteralSugar(site=site)
            if index == arm
            else FalseBoolLiteralSugar(site=site)
        )


def _exits_can_complete(exits) -> bool:
    from sugar_lift_py_tests.outcome.exit_set import Completed

    return any(isinstance(exit_, Completed) for exit_ in exits.exits)


def _route_handlers_over_exits(
    body_es,
    handlers: tuple,
    orelse: tuple,
    *,
    site,
    ctx=None,
    route_site=None,
    edge_keys=(),
    arm_effects=None,
):
    """Route each Halted raise through the first matching handler.

    Completed exits take ``else`` when present; unmatched halts propagate.
    Every resulting exit keeps its guard so finally fans across the partition.
    With a ``route_site`` every routed outcome also confirms the try's route
    slots (``_route_confirmation``).
    """
    from sugar_lift_py_tests.outcome.exit_set import ExitSet, Halted
    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        _ReducedBlock,
        reduce_block_to_exitset,
    )

    parts: list = []
    routed: list = []
    count = len(handlers)
    for exit_ in body_es.exits:
        if isinstance(exit_, Halted):
            for arm, part in _route_one_halt(
                exit_,
                handlers,
                site=site,
                ctx=ctx,
                with_arms=True,
                edge_keys=edge_keys,
            ):
                if arm is not None:
                    if arm_effects is not None:
                        # Whatever an arm halts with -- a re-raise of this very
                        # effect included -- left after the arm's own stores.
                        arm_effects.extend(
                            halted.effect
                            for halted in part.exits
                            if isinstance(halted, Halted)
                        )
                    facts = _route_confirmation(route_site, count, arm, site)
                    if facts:
                        part = _ground_route_on_faces(
                            _prepend_facts(part, facts), route_site, count, arm, site
                        )
                    routed.append((arm, part))
                parts.append(part)
            continue
        body_facts = _route_confirmation(route_site, count, None, site)
        if body_facts:
            exit_ = _ground_route_on_faces(
                _prepend_facts(ExitSet((exit_,)), body_facts),
                route_site,
                count,
                None,
                site,
            ).exits[0]

        if orelse:
            else_es = reduce_block_to_exitset(orelse, ctx)

            def _then_else(state):
                return else_es.sequence(
                    lambda else_state: ExitSet.completed(
                        _ReducedBlock(
                            entries=(*state.entries, *else_state.entries),
                            can_fall_through=else_state.can_fall_through,
                            fall_through=else_state.fall_through,
                            transforms=else_state.transforms,
                        )
                    )
                )

            if isinstance(exit_.value, _ReducedBlock):
                parts.append(ExitSet((exit_,)).sequence(_then_else))
            else:
                parts.append(ExitSet((exit_,)).sequence(lambda _s: else_es))
        else:
            parts.append(ExitSet((exit_,)))
        routed.append((None, parts[-1]))

    _ground_decided_route(routed, route_site, count, ctx, site)
    if not parts:
        return ExitSet.completed(
            _ReducedBlock(entries=(), can_fall_through=True, fall_through=())
        )
    result = parts[0]
    for part in parts[1:]:
        result = result.union(part)
    return result


def _route_one_halt(
    exit_, handlers: tuple, *, site, ctx, with_arms=False, edge_keys=()
) -> list:
    """Route ONE halted body exit through the handler list, in source order.

    Walks the arms carrying a residual: the exit as it still stands after every
    arm considered so far declined it. A settled match takes the whole residual
    and the walk is over. A settled miss leaves the residual untouched.

    A ``MatchRetained`` arm is the third case and the reason this is a walk
    rather than a scan. The arm owns a genuine two-way split, so it mints one,
    routes the residual into the handler under the obligation, and narrows the
    residual to the complement for the arms that follow. Nothing is admitted
    and nothing is dropped: whatever residual survives every arm leaves as the
    halt it always was, still red, under the conjunction of every complement.
    """
    from sugar_lift_py_tests.authenticated_exception_matching import (
        MatchDecided,
        MatchRetained,
    )
    from sugar_lift_py_tests.ir import not_
    from sugar_lift_py_tests.outcome.exit_set import ExitSet, partition

    def handler_exits(handler_body, slot_id):
        from sugar_lift_py_tests.in_flight_effect import bind_in_flight_effect
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            reduce_block_to_exitset,
        )

        # In-flight: bare re-raise. Observed: ``except ... as e`` / EffectRef
        # projects the same RaiseEffect this arm just matched — identity, not
        # a reconstructed E(). Observed must be installed BEFORE the body
        # reduces; prepending facts after the fact cannot authenticate a read
        # that already desugared to a pure coordinate.
        handler_ctx = bind_in_flight_effect(
            _ground_edges(ctx, edge_keys, exit_.effect),
            slot_id,
            exit_.effect,
            blame=site,
        )
        if slot_id is not None:
            observer = getattr(handler_ctx, "with_observed_effect", None)
            if observer is not None:
                handler_ctx = observer(slot_id, exit_.effect)
        handler_es = reduce_block_to_exitset(handler_body, handler_ctx)
        facts = _binding_facts_for(slot_id, exit_.effect, site)
        return _prepend_facts(handler_es, facts) if facts else handler_es

    parts: list = []
    residual = ExitSet((exit_,))

    def done():
        return parts if with_arms else [part for _arm, part in parts]

    for index, (matcher, handler_body, slot_id) in enumerate(handlers):
        if not residual.exits:
            return done()
        residual_guard = residual.exits[0].guard
        verdict, read_owes = _effect_match_verdict(
            exit_.effect, matcher, ctx, site=site
        )
        if isinstance(verdict, MatchDecided):
            if not verdict.value:
                residual = _beneath_type_read(residual, read_owes)
                continue
            parts.append(
                (
                    index,
                    _beneath_type_read(
                        handler_exits(handler_body, slot_id).guarded(residual_guard),
                        read_owes,
                    ),
                )
            )
            return done()
        if not isinstance(verdict, MatchRetained):
            raise TypeError(
                "except-arm verdict must be MatchDecided or MatchRetained; "
                f"got {type(verdict).__name__}"
            )
        # This arm owns the split, so it mints the faces rather than leaving the
        # exclusion legible only in the ``not_`` spelling of the two guards.
        caught_face, missed_face = partition(("try.except-identity", site, index))
        parts.append(
            (
                index,
                _beneath_type_read(
                    handler_exits(handler_body, slot_id)
                    .guarded(verdict.obligation, caught_face)
                    .guarded(residual_guard),
                    read_owes,
                ),
            )
        )
        residual = _beneath_type_read(
            residual.guarded(not_(verdict.obligation), missed_face), read_owes
        )
    if residual.exits:
        parts.append((None, residual))
    return done()


def _prepend_facts(exits, facts: tuple):
    """Attach EffectBinding facts to every completed exit's entry list.

    Each completed face continues as its record with the facts before its
    entries, composed through ``ExitSet.sequence``: the face's guard,
    partition testimony and ``owed`` ride on unchanged. Halts bypass."""
    from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock

    def prepended(state):
        if isinstance(state, _ReducedBlock):
            return ExitSet.completed(replace(state, entries=(*facts, *state.entries)))
        return ExitSet.completed(
            _ReducedBlock(
                entries=(*facts, state) if state is not None else facts,
                can_fall_through=True,
                fall_through=(),
            )
        )

    return exits.sequence(prepended)
