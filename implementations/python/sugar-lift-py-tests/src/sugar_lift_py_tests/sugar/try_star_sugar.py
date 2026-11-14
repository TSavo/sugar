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
- Finally restore preserves residual; finally terminate overrides.
- Leaf occurrence identities and nested topology survive partition/regroup.
- Ordinary ``RaiseEffect`` under ``except*`` stays loud (distinct from Try).
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


def _matcher_value(matcher, ctx):
    """One ``except*`` type operand's completed value, or None.

    The operand is read here, never retained for a caller: a deferred
    native-operation carrier is refused by name.
    """
    from sugar_lift_py_tests.outcome.exit_set import _require_exit_set

    return _require_exit_set(
        matcher.desugar(ctx), owner="TryStarSugar.handler-matcher"
    ).completed_value()


@dataclass(frozen=True)
class TryStarSugar(Sugar):
    body: tuple
    handlers: tuple
    orelse: tuple = ()
    finalbody: tuple = ()
    site: object = dataclass_field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        from sugar_lift_py_tests.caller_parameter_contract import (
            NativeOperationExitCarrierV1,
        )
        from sugar_lift_py_tests.effect.grouped_raise_effect import GroupedRaiseEffect
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
            _ReducedBlock,
            reduce_block_to_exitset,
            resumed,
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
            """
            if not isinstance(exit_.effect, GroupedRaiseEffect):
                raise SugarNotWritten(
                    blame=self.site,
                    owner="TryStarSugar.desugar",
                    observed=type(exit_.effect).__name__,
                    requested="GroupedRaiseEffect for except* routing",
                    fix="keep ordinary except and except* distinct",
                )
            original = exit_.effect
            # Frontier: one face per body halt, then each handler branches it.
            # The face begins from the state the halt carries (``resumed``).
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
            # Faces that leave the residual walk (non-raise halts).
            retained: list = []

            for matchers, handler_body, slot_id in self.handlers:
                if not isinstance(matchers, tuple):
                    matchers = (matchers,)
                next_frontier: list[_StarFace] = []
                for face in frontier:
                    # One alternative per split of this face by the handler's
                    # types: ``(path, residual, matched parts)``.  A leaf whose
                    # match the one matcher retained splits the face two ways
                    # (``GroupedRaiseEffect.partition``), each path guarded by
                    # its obligation or complement and carrying its face, as
                    # ordinary ``except`` routes an undecided match.
                    alternatives = [(face.path, face.residual, ())]
                    for matcher in matchers:
                        expected = _matcher_value(matcher, face.state.context)
                        if expected is None:
                            raise SugarNotWritten(
                                blame=self.site,
                                owner="TryStarSugar.desugar",
                                observed="symbolic except* type",
                                requested="authenticated subtype partition operand",
                                fix="keep symbolic subtype partition typed loud",
                            )
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
                        # The handler resumes from the face's record: the
                        # halt's, then what every earlier handler on this
                        # path left.
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
                            handler_ctx = handler_ctx.with_observed_effect(
                                slot_id, matched
                            )
                        handler_exits = reduce_block_to_exitset(
                            handler_body,
                            handler_ctx,
                            after=replace(record, context=handler_ctx),
                        )
                        # The handler runs beneath this split's path:
                        # ``sequence`` conjoins the path's guard, faces and
                        # ``owed`` onto every handler arm. One next face per
                        # composed arm.  The frontier is built from the
                        # handler's arms now: a handler still waiting on its
                        # caller's actuals, whose carrier ``sequence``
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
                frontier = next_frontier

            # Emit residual / exceptional per face — regroup only within a face
            # (equal guard path). Never AND guards across alternative faces.
            # Completed only when residual is empty and no exceptional remains.
            for face in frontier:
                effects = list(face.exceptional)
                if face.residual.children:
                    effects.append(face.residual)
                if effects:
                    # Never None: a face that owes a raise answers it (#7825).
                    # It raises beneath its path, keeping the path's guard,
                    # faces and ``owed``.
                    raised = regroup_except_star(original, effects)
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

        def _walk_handler_arms(
            composed, face, handler_residual, next_frontier, retained
        ):
            """One next face per arm a handler composed beneath its path."""
            for arm in composed.exits:
                if isinstance(arm, Halted):
                    exceptional = face.exceptional
                    if _is_exceptional_raise(arm.effect):
                        exceptional = (*exceptional, arm.effect)
                    else:
                        # Non-raise halt leaves the residual walk as an exit.
                        retained.append(ExitSet((arm,)))
                    next_state = (
                        arm.state
                        if isinstance(arm.state, _ReducedBlock)
                        else face.state
                    )
                else:
                    # Handler fall-through is NOT a try* completed edge while
                    # an unmatched residual remains — Python has no completed
                    # edge there. Only advance temporal state on the
                    # residual/exceptional frontier.
                    exceptional = face.exceptional
                    next_state = (
                        arm.value
                        if isinstance(arm.value, _ReducedBlock)
                        else face.state
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
                cleanup = reduce_block_to_exitset(self.finalbody, ctx)
                from sugar_lift_py_tests.floor.return_value import ReturnValue

                def restores(value):
                    return not (
                        isinstance(value, _ReducedBlock)
                        and (
                            not value.can_fall_through
                            or any(isinstance(e, ReturnValue) for e in value.entries)
                        )
                    )

                result = result.and_finally(lambda: cleanup, cleanup_restores=restores)
            # The try*'s own faces: a halt stays a halted arm, never an entry of
            # a completed record (#7826).
            return result.normalize()

        def route(body):
            """Route the body's faces: completed arms run the ``else``, the
            halts the try* owns run the handlers beneath them."""
            return close(
                body.sequence(after_body, consume=handled)
                if body.exits
                else ExitSet.completed(_ReducedBlock((), True, ()))
            )

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


def _is_exceptional_raise(effect) -> bool:
    from sugar_lift_py_tests.effect.grouped_raise_effect import GroupedRaiseEffect
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect

    return isinstance(effect, (RaiseEffect, GroupedRaiseEffect))
