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

from sugar_lift_py_tests.outcome import Outcome
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

    def desugar(self, ctx: object = None) -> Outcome:
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
        from sugar_lift_py_tests.floor.return_value import ReturnValue
        from sugar_lift_py_tests.sugar.exit_set_routing import (
            exitset_to_outcome,
            promote_raise_halts,
        )
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            _ReducedBlock,
            reduce_block_to_exitset,
        )

        pre_finally = _route_handlers_over_exits(
            promote_raise_halts(body_es),
            self.handlers,
            self.orelse,
            site=self.site,
            ctx=ctx,
        )

        if not self.finalbody:
            return exitset_to_outcome(pre_finally)

        cleanup_es = reduce_block_to_exitset(self.finalbody, ctx)

        def _cleanup():
            return cleanup_es

        def _restores(value: object) -> bool:
            if isinstance(value, _ReducedBlock):
                if not value.can_fall_through:
                    return False
                if any(isinstance(e, ReturnValue) for e in value.entries):
                    return False
                return True
            return True

        after = pre_finally.and_finally(_cleanup, cleanup_restores=_restores)
        return exitset_to_outcome(after)


def _effect_match_verdict(effect, matcher, ctx=None):
    """Bare except matches any raise; typed arms use constructed identity.

    The codomain is the shared matcher's: ``MatchDecided`` when the arm settles
    at lift, ``MatchRetained`` when the identity test is real and open. The
    caller must route BOTH faces of a retention -- never treat it as a match
    and never as a miss.
    """
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
    from sugar_lift_py_tests.authenticated_exception_matching import (
        MatchDecided,
        matches_raise_effect,
    )
    from sugar_lift_py_tests.outcome import Complete
    from sugar_source_tree.panic import SugarNotWritten

    if not isinstance(effect, RaiseEffect):
        return MatchDecided(False)
    if matcher is None:
        return MatchDecided(True)
    expected = matcher.desugar(ctx)
    if not isinstance(expected, Complete):
        raise SugarNotWritten(
            blame=effect.occurrence_id,
            owner="TrySugar._effect_matches",
            observed="except type did not construct a completed type operand",
            requested="an authenticated exception-type value",
            fix="keep unresolved handler types loud",
        )
    return matches_raise_effect(effect, expected.value)


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


def _route_handlers_over_exits(
    body_es,
    handlers: tuple,
    orelse: tuple,
    *,
    site,
    ctx=None,
):
    """Route each Halted raise through the first matching handler.

    Completed exits take ``else`` when present; unmatched halts propagate.
    Every resulting exit keeps its guard so finally fans across the partition.
    """
    from sugar_lift_py_tests.outcome.exit_set import ExitSet, Halted
    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        _ReducedBlock,
        reduce_block_to_exitset,
    )

    parts: list = []
    for exit_ in body_es.exits:
        if isinstance(exit_, Halted):
            parts.extend(_route_one_halt(exit_, handlers, site=site, ctx=ctx))
            continue

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

    if not parts:
        return ExitSet.completed(
            _ReducedBlock(entries=(), can_fall_through=True, fall_through=())
        )
    result = parts[0]
    for part in parts[1:]:
        result = result.union(part)
    return result


def _route_one_halt(exit_, handlers: tuple, *, site, ctx) -> list:
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
        handler_ctx = bind_in_flight_effect(ctx, slot_id, exit_.effect, blame=site)
        if slot_id is not None:
            observer = getattr(handler_ctx, "with_observed_effect", None)
            if observer is not None:
                handler_ctx = observer(slot_id, exit_.effect)
        handler_es = reduce_block_to_exitset(handler_body, handler_ctx)
        facts = _binding_facts_for(slot_id, exit_.effect, site)
        return _prepend_facts(handler_es, facts) if facts else handler_es

    parts: list = []
    residual = ExitSet((exit_,))
    for index, (matcher, handler_body, slot_id) in enumerate(handlers):
        if not residual.exits:
            return parts
        residual_guard = residual.exits[0].guard
        verdict = _effect_match_verdict(exit_.effect, matcher, ctx)
        if isinstance(verdict, MatchDecided):
            if not verdict.value:
                continue
            parts.append(handler_exits(handler_body, slot_id).guarded(residual_guard))
            return parts
        if not isinstance(verdict, MatchRetained):
            raise TypeError(
                "except-arm verdict must be MatchDecided or MatchRetained; "
                f"got {type(verdict).__name__}"
            )
        # This arm owns the split, so it mints the faces rather than leaving the
        # exclusion legible only in the ``not_`` spelling of the two guards.
        caught_face, missed_face = partition(("try.except-identity", site, index))
        parts.append(
            handler_exits(handler_body, slot_id)
            .guarded(verdict.obligation, caught_face)
            .guarded(residual_guard)
        )
        residual = residual.guarded(not_(verdict.obligation), missed_face)
    if residual.exits:
        parts.append(residual)
    return parts


def _prepend_facts(exits, facts: tuple):
    """Attach EffectBinding facts to every completed exit's entry list."""
    from sugar_lift_py_tests.outcome.exit_set import Completed, ExitSet, Halted
    from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock

    out = []
    for exit_ in exits.exits:
        if isinstance(exit_, Halted):
            out.append(exit_)
            continue
        state = exit_.value
        if isinstance(state, _ReducedBlock):
            out.append(
                Completed(
                    exit_.guard,
                    replace(state, entries=(*facts, *state.entries)),
                )
            )
        else:
            out.append(
                Completed(
                    exit_.guard,
                    _ReducedBlock(
                        entries=(*facts, state) if state is not None else facts,
                        can_fall_through=True,
                        fall_through=(),
                    ),
                )
            )
    return ExitSet(tuple(out)).normalize()
