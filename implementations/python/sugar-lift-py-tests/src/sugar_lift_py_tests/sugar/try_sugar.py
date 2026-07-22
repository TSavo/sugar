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

from sugar_lift_py_tests.outcome import Complete, Outcome
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
        from sugar_lift_py_tests.outcome.exit_set import ExitSet
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            _ReducedBlock,
            reduce_block_to_exitset,
        )

        del ctx

        # 1. Body as guarded ExitSet (promote embedded conditional raises).
        body_es = _promote_raise_halts(reduce_block_to_exitset(self.body))

        # 2. Route handlers over Halted exits; Completed (+ else) pass through.
        pre_finally = _route_handlers_over_exits(
            body_es,
            self.handlers,
            self.orelse,
            site=self.site,
        )

        # 3. finally over every exit.
        if not self.finalbody:
            return _exitset_to_outcome(pre_finally)

        cleanup_es = reduce_block_to_exitset(self.finalbody)

        def _cleanup():
            return cleanup_es

        def _restores(value: object) -> bool:
            # Fall-through completed cleanup restores the try exit.
            # Terminal return in finally supersedes.
            if isinstance(value, _ReducedBlock):
                if not value.can_fall_through:
                    return False
                if any(isinstance(e, ReturnValue) for e in value.entries):
                    return False
                return True
            return True

        after = pre_finally.and_finally(_cleanup, cleanup_restores=_restores)
        return _exitset_to_outcome(after)


def _is_hard_raise(entry) -> bool:
    """True when entry is a raise Incomplete that halts control flow."""
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
    from sugar_lift_py_tests.outcome import Incomplete

    if not isinstance(entry, Incomplete):
        return False
    if not isinstance(entry.effect, RaiseEffect):
        return False
    # Store-like effects continue; raises halt (follow default).
    return not entry.follow().continues


def _guard_from_conditions(exit_guard, branch_conditions):
    from sugar_lift_py_tests.ir import and_
    from sugar_lift_py_tests.outcome.exit_set import true_guard

    parts = []
    if exit_guard is not None and exit_guard != true_guard():
        parts.append(exit_guard)
    parts.extend(branch_conditions)
    if not parts:
        return true_guard()
    if len(parts) == 1:
        return parts[0]
    return and_(list(parts))


def _promote_raise_halts(exits: "ExitSet") -> "ExitSet":
    """Lift Incomplete(raise) entries out of Completed blocks into Halted exits.

    ``if c: raise`` flattens through IfSugar into a single Completed whose
    entries embed ``Incomplete(..., branch_conditions=(c,))``. Without this
    promotion, handler routing cannot see a Halted face and the complementary
    completion path is lost when the linear adapter consumes the raise.
    """
    from sugar_lift_py_tests.outcome.exit_set import Completed, ExitSet, Halted
    from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock

    promoted: list = []
    for exit_ in exits.exits:
        if isinstance(exit_, Halted):
            promoted.append(exit_)
            continue
        if not isinstance(exit_, Completed):
            promoted.append(exit_)
            continue
        state = exit_.value
        if not isinstance(state, _ReducedBlock):
            promoted.append(exit_)
            continue

        remaining: list = []
        saw_halt = False
        for entry in state.entries:
            if _is_hard_raise(entry):
                saw_halt = True
                guard = _guard_from_conditions(
                    exit_.guard, entry.branch_conditions
                )
                promoted.append(Halted(guard, entry.effect))
            else:
                remaining.append(entry)

        if not saw_halt:
            promoted.append(exit_)
            continue

        # Complementary completed face: non-raise entries (already self-guarded
        # when they came from if-flattening) under the original exit guard.
        if remaining or state.can_fall_through:
            promoted.append(
                Completed(
                    exit_.guard,
                    replace(
                        state,
                        entries=tuple(remaining),
                    ),
                )
            )
    return ExitSet(tuple(promoted)).normalize()


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
    from sugar_lift_py_tests.outcome.exit_set import Completed, ExitSet, Halted
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
                # Handler runs only under the halt's guard (c: handler path).
                parts.append(handler_es.guarded(exit_.guard))
                matched = True
                break
            if not matched:
                parts.append(ExitSet((exit_,)))
            continue

        # Completed: optional else under the same guard.
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
                parts.append(
                    ExitSet((exit_,)).sequence(_then_else)
                )
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


def _exitset_to_outcome(exits) -> Outcome:
    """Collapse ExitSet to the linear Complete(BlockValue) / Incomplete view."""
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.floor.return_value import ReturnValue
    from sugar_lift_py_tests.outcome import Incomplete
    from sugar_lift_py_tests.outcome.exit_set import Completed, Halted, true_guard
    from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock

    from sugar_lift_py_tests.outcome import Complete as OutcomeComplete

    collapsed = exits.collapse()
    if isinstance(collapsed, Incomplete):
        # Pure halt: still expose as BlockValue red testimony so later
        # statements / invs see the effect entry (and finally supersede is
        # already applied).
        return Complete(BlockValue((collapsed,), can_fall_through=False))
    if isinstance(collapsed, OutcomeComplete):
        value = collapsed.value
        if isinstance(value, _ReducedBlock):
            return Complete(
                BlockValue(
                    value.entries,
                    fall_through=value.fall_through,
                    can_fall_through=value.can_fall_through,
                )
            )
        # Terminal cleanup completed with raw value (rare)
        if isinstance(value, ReturnValue):
            return Complete(BlockValue((value,), can_fall_through=False))
        return Complete(BlockValue((), can_fall_through=True))

    # Multi-exit: flatten every exit under its guard so dual posts survive.
    entries: list = []
    can_fall = False
    for exit_ in exits.normalize().exits:
        if isinstance(exit_, Halted):
            inc = Incomplete(exit_.effect)
            if exit_.guard != true_guard():
                inc = Incomplete(exit_.effect, branch_conditions=(exit_.guard,))
            entries.append(inc)
        elif isinstance(exit_, Completed):
            value = exit_.value
            if isinstance(value, _ReducedBlock):
                if exit_.guard != true_guard():
                    entries.extend(
                        entry.guarded(exit_.guard) for entry in value.entries
                    )
                else:
                    entries.extend(value.entries)
                can_fall = can_fall or value.can_fall_through
            elif isinstance(value, ReturnValue):
                if exit_.guard != true_guard():
                    entries.append(value.guarded(exit_.guard))
                else:
                    entries.append(value)
    return Complete(BlockValue(tuple(entries), can_fall_through=can_fall))
