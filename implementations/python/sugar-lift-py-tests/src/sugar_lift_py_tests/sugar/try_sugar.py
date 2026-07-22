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
    """handlers: ((EffectMatcher|None, body_sugars, slot_id|None), ...)"""

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
        from sugar_lift_py_tests.floor.return_value import ReturnValue
        from sugar_lift_py_tests.sugar.exit_set_routing import (
            exitset_to_outcome,
            promote_raise_halts,
        )
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            _ReducedBlock,
            reduce_block_to_exitset,
        )

        del ctx

        body_es = promote_raise_halts(reduce_block_to_exitset(self.body))
        pre_finally = _route_handlers_over_exits(
            body_es,
            self.handlers,
            self.orelse,
            site=self.site,
        )

        if not self.finalbody:
            return exitset_to_outcome(pre_finally)

        cleanup_es = reduce_block_to_exitset(self.finalbody)

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


def _effect_matches(effect, matcher) -> bool:
    """Bare except (matcher is None) matches any raise; typed arms exact name."""
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect

    if not isinstance(effect, RaiseEffect):
        return False
    if matcher is None:
        return True
    if getattr(matcher, "kind", None) != "raise":
        return False
    return effect.exception_name == matcher.name


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
            matched = False
            for matcher, handler_body, slot_id in handlers:
                if not _effect_matches(exit_.effect, matcher):
                    continue
                handler_es = reduce_block_to_exitset(handler_body)
                facts = _binding_facts_for(slot_id, exit_.effect, site)
                if facts:
                    handler_es = _prepend_facts(handler_es, facts)
                parts.append(handler_es.guarded(exit_.guard))
                matched = True
                break
            if not matched:
                parts.append(ExitSet((exit_,)))
            continue

        if orelse:
            else_es = reduce_block_to_exitset(orelse)

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
