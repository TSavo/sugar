"""``except*`` subgroup routing over authenticated ``GroupedRaiseEffect`` trees.

Laws (owned here; ExitSet/carrier untouched):

- Partition each body ``GroupedRaiseEffect`` by authenticated handler type.
  A leaf whose match the one matcher retains splits the face two ways
  (matched under the obligation, residual under its complement), as ordinary
  ``except`` routes an undecided match: never a refusal.
- Matching subgroup reaches its handler once (type-tuple = one body run).
- Unmatched residual continues to subsequent handlers in source order.
- Temporal state is an ExitSet of **per-face** handler states — never a single
  scalar accumulator. Each handler face branches the frontier independently.
- Every ExitSet face carries the enclosing body guard conjoined.
- Handler fall-through is **not** a try* completed edge while residual remains;
  residual continues and ultimately halts unless later consumed.
- Exceptional raise effects regroup **only within equal guards** (never AND
  mutually exclusive alternative faces into one impossible guard).
- What is a raised exception is read in one place (``is_exception_effect``,
  as ordinary ``except`` reads it), for the body's halt and a handler's alike:
  a handler's undetermined raise regroups with the residual like any other.
- Finally restore preserves residual; finally terminate overrides.
- Leaf occurrence identities and nested topology survive partition/regroup.
- A plain raise (decided or undetermined) is matched as the one-member group
  CPython wraps it in; what leaves is the one exception CPython raises: the
  handler's raise, or the unmatched original itself, never wrapped.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field, replace

from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class _StarFace:
    """One except* routing face: residual + temporal state under one path."""

    # The path into this face: ONE completed arm whose value is the temporal
    # state (a ``_ReducedBlock``). Its guard, faces and ``owed`` are what
    # ``ExitSet.sequence`` composed from every handler arm the face ran
    # through; everything emitted from the face runs beneath it, so nothing
    # restates them by hand.
    path: object  # ExitSet
    residual: object  # GroupedRaiseEffect
    # Exceptional raises collected on THIS face's guard path only.
    exceptional: tuple

    @property
    def state(self):
        (arm,) = self.path.exits
        return arm.value


def _matcher_read(matcher, ctx):
    """One ``except*`` type operand's read: every face of it.

    The operand is read here, never retained for a caller: a deferred
    native-operation carrier is refused by name.  Each face keeps its guard,
    faces and ``owed`` (the undecided read of a class only a star import may
    bind owes the ``undecided`` member; a read that may raise has a halted
    face), so the router continues beneath every face, as ordinary
    ``except`` does (``TrySugar._effect_match_verdict``).
    """
    from sugar_lift_py_tests.outcome.exit_set import _require_exit_set

    return _require_exit_set(
        matcher.desugar(ctx), owner="TryStarSugar.handler-matcher"
    )


def _beneath_read_faces(path, read):
    """``path`` -- one routing face's completed arm -- continued beneath
    every face of one arm type's ``read`` (``ExitSet.sequence``).

    Answers ``(halts, reads)``.  A halted face is the ``try*``'s halt right
    there, as for ordinary ``except`` (``try_sugar._beneath_read_face``):
    Python raises it while reading the handler's types, no later handler
    sees it and the ``finally`` does; it is recorded where the face stood
    (its temporal state) when the read offers none.  It leaves alone: CPython
    evaluates an ``except*`` type under the handler block's cleanup, which
    re-raises the new exception (``POP_EXCEPT_AND_RERAISE``), not under
    ``PREP_RERAISE_STAR``, so neither the residual nor what an earlier
    handler on this path raised is regrouped with it.  Each completed face
    gives the path under that face's guard, faces and ``owed``, still the
    one arm holding the face's state, paired with the type value it read.
    A face whose guard cannot hold beneath the path is dropped by
    ``sequence``, never invented.
    """
    from sugar_lift_py_tests.outcome.exit_set import ExitSet, Halted

    halts = []
    reads = []
    for face in read.exits:
        if isinstance(face, Halted):

            def raised(state, face=face):
                return ExitSet(
                    (face if face.state is not None else replace(face, state=state),)
                )

            halts.append(path.sequence(raised))
            continue

        def continued(state, face=face):
            return ExitSet((face,)).sequence(
                lambda _type, state=state: ExitSet.completed(state)
            )

        beneath = path.sequence(continued)
        if beneath.exits:
            reads.append((beneath, face.value))
    return halts, reads


def _wrapped(effect):
    """The group ``except*`` matches a plain raised exception as.

    CPython's ``_PyEval_ExceptionGroupMatch`` wraps a naked exception in a
    one-member group (``_PyExc_CreateExceptionGroup("", (exc,))``, which
    calls ``BaseExceptionGroup``), so the member decides the group's class
    exactly as ``GroupedRaiseSugar`` decides a constructed group's
    (``_is_exception``, the one matcher): ``ExceptionGroup`` for an
    ``Exception``, ``BaseExceptionGroup`` otherwise, undecided (no class)
    when the member's class is.  An undetermined leaf (an unanswered
    construction, ``OSError(e, 'x')``) is a member like any other: its
    matches are retained and split two ways (``GroupedRaiseEffect.partition``),
    and the debt its construction owes rides on the halt this runs beneath.
    """
    from sugar_lift_py_tests.effect.grouped_raise_effect import GroupedRaiseEffect
    from sugar_lift_py_tests.floor.ground_exit import _builtin_exception_identity
    from sugar_lift_py_tests.floor.string_value import StringValue
    from sugar_lift_py_tests.sugar.grouped_raise_sugar import _is_exception

    occurrence = f"except-star.wrap:{effect.occurrence_id}"
    exception = _is_exception(effect)
    identity, mro = None, None
    if exception is not None:
        group_class = "ExceptionGroup" if exception else "BaseExceptionGroup"
        identity, mro = _builtin_exception_identity(group_class)
    return GroupedRaiseEffect(
        occurrence,
        StringValue(""),
        (effect,),
        occurrence=occurrence,
        exception_type_coordinate=identity,
        exception_type_mro=mro,
        # The wrapped exception's own halt site: the group halts where it did.
        site=getattr(effect, "site", None),
    )


@dataclass(frozen=True)
class TryStarSugar(Sugar):
    body: tuple
    handlers: tuple
    orelse: tuple = ()
    finalbody: tuple = ()
    site: object = dataclass_field(compare=False, default=None)
    #: ``finally`` substituted under the state a halt carries into it (the
    #: one temporal rewrite, ``Try.substitute``, which ``TryStar`` runs);
    #: None when that is the completion state.  Read by the one ``finally``
    #: (``try_sugar._and_finally_with_raise_context``), as ``TrySugar``'s is.
    finalbody_halted: object = None

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        from sugar_lift_py_tests.caller_parameter_contract import (
            NativeOperationExitCarrierV1,
        )
        from sugar_lift_py_tests.effect.grouped_raise_effect import (
            GroupedRaiseEffect,
            is_exception_effect,
        )
        from sugar_lift_py_tests.effect_router import (
            regroup_except_star,
            route_except_star,
        )
        from sugar_lift_py_tests.in_flight_effect import bind_in_flight_effect
        from sugar_lift_py_tests.outcome.exit_set import (
            ExitSet,
            Halted,
            _require_exit_set,
        )
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            face_record,
            reduce_block_to_exitset,
            resumed,
        )
        from sugar_lift_py_tests.sugar.try_sugar import (
            _and_finally_with_raise_context,
            _try_outcome,
        )
        from sugar_source_tree.panic import SugarNotWritten

        body = reduce_block_to_exitset(self.body, ctx)

        def after_body(value):
            # The ``else`` continues after the body's completed record.
            if self.orelse:
                return reduce_block_to_exitset(self.orelse, ctx, after=value)
            return ExitSet.completed(value)

        def handled(exit_):
            """The continuation beneath one body halt the try* owns.

            Built from the halt's point on: the frontier starts under truth,
            with no faces and owing nothing, and ``sequence`` conjoins the
            body halt's guard, faces and ``owed`` onto every arm answered here.

            What the handlers route is a raised exception, read the one way
            ordinary ``except`` reads it (``is_exception_effect``).  A plain
            raise (a ``RaiseEffect``, or the ``UndeterminedRaiseEffect`` of an
            operation nothing here answered: an unanswered construction, the
            truth of an undecided ``if`` test) is matched as the one-member
            group CPython wraps it in (``_wrapped``), each handler's match
            asked of the one matcher; ``naked`` keeps it, since what leaves is
            then the one exception CPython raises (below), never a group of
            the residual.
            """
            if not is_exception_effect(exit_.effect):
                raise SugarNotWritten(
                    blame=self.site,
                    owner="TryStarSugar.desugar",
                    observed=type(exit_.effect).__name__,
                    requested="a raise (plain or grouped) for except* routing",
                    fix="route this halt kind through except* or let it pass",
                )
            naked = None
            if isinstance(exit_.effect, GroupedRaiseEffect):
                original = exit_.effect
            else:
                naked = exit_.effect
                original = _wrapped(naked)
            # Frontier: one face per body halt, then each handler branches it.
            # The face begins from the state the halt carries (``resumed``),
            # without the ``return`` entries its record holds: none is live
            # on the halt's arm (as for ``except``).
            frontier: list[_StarFace] = [
                _StarFace(
                    path=ExitSet.completed(
                        resumed(
                            exit_.state,
                            ctx,
                            owner="TryStarSugar.handler",
                            blame=self.site,
                        )
                    ),
                    residual=original,
                    exceptional=(),
                )
            ]
            # Faces that leave the residual walk (non-raise halts, and the
            # halt of a handler type's read).
            retained: list = []

            for matchers, handler_body, slot_id in self.handlers:
                if not isinstance(matchers, tuple):
                    matchers = (matchers,)
                next_frontier: list[_StarFace] = []
                for face in frontier:
                    # Python reads the handler's types (a tuple, left to
                    # right) whenever the group reaches the handler, matched
                    # or not, and only then matches.  Every face of every read
                    # is carried (``_beneath_read_faces``): a halted face is
                    # the try*'s halt here, which no later handler sees;
                    # beneath each completed face the path keeps the read's
                    # guard, faces and ``owed`` (every path that passed the
                    # handler owes what its read owes), and routing goes on
                    # over the types that face read.
                    read_paths = [(face.path, ())]
                    for matcher in matchers:
                        read = _matcher_read(matcher, face.state.context)
                        next_reads = []
                        for read_path, expecteds in read_paths:
                            halts, reads = _beneath_read_faces(read_path, read)
                            retained.extend(halts)
                            next_reads.extend(
                                (beneath, (*expecteds, expected))
                                for beneath, expected in reads
                            )
                        read_paths = next_reads
                    for read_path, expecteds in read_paths:
                        _route_read_types(
                            face,
                            read_path,
                            expecteds,
                            handler_body,
                            slot_id,
                            next_frontier,
                            retained,
                        )
                frontier = next_frontier

            # Emit residual / exceptional per face — regroup only within a face
            # (equal guard path). Never AND guards across alternative faces.
            # Completed only when residual is empty and no exceptional remains.
            for face in frontier:
                effects = list(face.exceptional)
                if face.residual.children:
                    effects.append(face.residual)
                if effects and naked is not None:
                    # A plain raise was matched as its one-member group, so
                    # on any path at most one handler ran over it: CPython's
                    # ``_PyExc_PrepReraiseStar`` raises that one exception as
                    # it is -- the handler's raise (a bare ``raise`` re-raises
                    # the wrapping group), or, unmatched, the original
                    # exception itself, never wrapped.
                    if len(effects) != 1:
                        raise SugarNotWritten(
                            blame=self.site,
                            owner="TryStarSugar.desugar",
                            observed=f"{len(effects)} exceptions from a plain raise",
                            requested="at most one exception from a plain raise",
                            fix="route a plain raise to at most one handler",
                        )
                    raised = face.exceptional[0] if face.exceptional else naked
                elif effects:
                    # Never None: a face that owes a raise answers it (#7825).
                    # It raises beneath its path, keeping the path's guard,
                    # faces and ``owed``.
                    raised = regroup_except_star(original, effects)
                if effects:
                    retained.append(
                        face.path.sequence(
                            lambda state, raised=raised: ExitSet.halted(
                                raised, state=state
                            )
                        )
                    )
                else:
                    retained.append(face.path)

            # No arm is invented: when no path leaves the handlers (every arm
            # was unsatisfiable, so ``sequence`` dropped it), the continuation
            # is exactly the empty set ``sequence`` composed. A raise is never
            # a completion (#7825). The leaving faces are siblings: one join.
            return ExitSet(()).union(*retained)

        def _route_read_types(
            face,
            read_path,
            expecteds,
            handler_body,
            slot_id,
            next_frontier,
            retained,
        ):
            """Route ``face``'s residual through one handler over the types
            one completed face of its read holds, beneath ``read_path``.

            One alternative per split of the residual by those types:
            ``(path, residual, matched parts)``.  A leaf whose match the one
            matcher retained splits the path two ways
            (``GroupedRaiseEffect.partition``), each guarded by its
            obligation or complement and carrying its face, as ordinary
            ``except`` routes an undecided match."""
            alternatives = [(read_path, face.residual, ())]
            for expected in expecteds:
                split_alternatives = []
                for path, residual, parts in alternatives:
                    routed = route_except_star(
                        residual,
                        expected,
                        slot_id=slot_id,
                        site=self.site,
                    )
                    if routed is None:
                        split_alternatives.append((path, residual, parts))
                        continue
                    for outcome in routed:
                        split_path = path
                        for formula, split_face in outcome.conditions:
                            split_path = split_path.guarded(formula, split_face)
                        if not split_path.exits:
                            continue
                        split_alternatives.append(
                            (
                                split_path,
                                outcome.residual,
                                (
                                    (*parts, outcome.matched)
                                    if outcome.matched.children
                                    else parts
                                ),
                            )
                        )
                alternatives = split_alternatives
            for path, handler_residual, matched_parts in alternatives:
                if not matched_parts:
                    # This path does not match this handler — residual
                    # continues.
                    next_frontier.append(
                        _StarFace(
                            path=path,
                            residual=handler_residual,
                            exceptional=face.exceptional,
                        )
                    )
                    continue
                matched = regroup_except_star(face.residual, matched_parts)
                # The handler resumes from the face's record: the halt's,
                # then what every earlier handler on this path left.
                record = resumed(
                    face.state,
                    ctx,
                    owner="TryStarSugar.handler",
                    blame=self.site,
                )
                handler_ctx = bind_in_flight_effect(
                    record.context, slot_id, matched, blame=self.site
                )
                if slot_id is not None:
                    # Shared typed ReduceContext surface.
                    handler_ctx = handler_ctx.with_observed_effect(slot_id, matched)
                handler_exits = reduce_block_to_exitset(
                    handler_body,
                    handler_ctx,
                    after=replace(record, context=handler_ctx),
                )
                # The handler runs beneath this split's path: ``sequence``
                # conjoins the path's guard, faces and ``owed`` onto every
                # handler arm. One next face per composed arm.  The frontier
                # is built from the handler's arms now: a handler still
                # waiting on its caller's actuals, whose carrier ``sequence``
                # composed, is refused by name here.
                composed = _require_exit_set(
                    path.sequence(lambda _state, exits=handler_exits: exits),
                    owner="TryStarSugar.handler",
                )
                _walk_handler_arms(
                    composed,
                    face,
                    handler_residual,
                    next_frontier,
                    retained,
                )

        def _walk_handler_arms(
            composed, face, handler_residual, next_frontier, retained
        ):
            """One next face per arm a handler composed beneath its path."""
            for arm in composed.exits:
                if isinstance(arm, Halted):
                    exceptional = face.exceptional
                    # A handler's raise is an exception by the one reading the
                    # body's halt is routed by (``is_exception_effect``): an
                    # undetermined raise (a may-raise operation in the handler)
                    # joins the residual like any other, never left beside a
                    # completion of the path it halted.
                    if is_exception_effect(arm.effect):
                        exceptional = (*exceptional, arm.effect)
                    else:
                        # Non-raise halt leaves the residual walk as an exit.
                        retained.append(ExitSet((arm,)))
                else:
                    # Handler fall-through is NOT a try* completed edge while
                    # an unmatched residual remains — Python has no completed
                    # edge there. Only advance temporal state on the
                    # residual/exceptional frontier.
                    exceptional = face.exceptional
                # The frontier walks on from the record the handler arm left
                # (its completed block, or the record its halt carries): the
                # handler's stores are never dropped for an earlier record.
                # An arm with no record is stopped by name (``face_record``).
                next_state = face_record(
                    arm, owner="TryStarSugar.handler", blame=self.site
                )

                # The next face's path is this arm continuing as its temporal
                # state (``sequence``; ``consume=`` for a halted arm): the
                # arm's guard, faces and ``owed``.
                def walk_on(_reached, state=next_state):
                    return ExitSet.completed(state)

                next_frontier.append(
                    _StarFace(
                        path=ExitSet((arm,)).sequence(walk_on, consume=walk_on),
                        residual=handler_residual,
                        exceptional=exceptional,
                    )
                )

        def close(result):
            """The ``finally`` over every arm the try* composed, then its own
            faces.  An ``else`` suite still waiting on its caller's actuals
            (``sequence`` handed its carrier on) is closed once it discharges."""
            if isinstance(result, NativeOperationExitCarrierV1):
                return result.after_discharge(
                    lambda projected: close(
                        _require_exit_set(projected, owner="TryStarSugar.orelse")
                    )
                )
            if self.finalbody:
                # The one ``finally`` (``try_sugar``): it continues from the
                # state each arm brings it -- a completed record, or the
                # record a halt carries -- and re-emits that arm's exit after
                # it unless it exits itself. A ``finally`` still waiting on
                # the caller's actuals is composed once they discharge
                # (``_finally_beneath``).  A halted arm runs the copy
                # substituted for the halted faces (``finalbody_halted``),
                # a completed arm the completion copy.  The rewrite's
                # ``try-route`` and ``try-edge`` slots are not grounded
                # here: a binding joined over one is read under both of its
                # arms (``GuardedBindingReadSugar``).
                result = _and_finally_with_raise_context(
                    result,
                    self.finalbody,
                    ctx=ctx,
                    site=self.site,
                    finalbody_halted=self.finalbody_halted,
                )
            # The try*'s own faces, read the one way a ``try``'s are
            # (``_try_outcome``): a halt stays a halted arm, never an entry
            # of a completed record (#7826), and faces still waiting on the
            # caller's actuals are read once they discharge.
            return _try_outcome(result)

        def route(body):
            """Route the body's faces: completed arms run the ``else``, the
            halts the try* owns run the handlers beneath them.  A body with
            no face (every arm unsatisfiable) leaves the try* with none: an
            empty arm set is never a completion, so none is made up."""
            return close(body.sequence(after_body, consume=handled))

        if isinstance(body, NativeOperationExitCarrierV1):
            # The body still waits on its caller's actuals: once it discharges,
            # its faces are routed exactly as a body reduced here is, so every
            # halt it raises reaches the handlers with its guard, faces and
            # ``owed``.
            return body.after_discharge(
                lambda projected: route(
                    _require_exit_set(projected, owner="TryStarSugar.body")
                )
            )
        return route(_require_exit_set(body, owner="TryStarSugar.body"))
