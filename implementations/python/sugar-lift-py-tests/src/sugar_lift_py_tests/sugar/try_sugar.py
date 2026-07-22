"""`try` effect routing + finally over ExitSet.

except-as is tree-rewritten to EffectRef(slot); route_except matches once and
emits EffectBinding facts. finally runs on every exit:

- cleanup fall-through restores the incoming exit
- cleanup halt supersedes
- cleanup terminal completion (return) supersedes
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

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
        from sugar_lift_py_tests.effect_router import (
            _first_effect_of_kind,
            route_except,
        )
        from sugar_lift_py_tests.floor.block_value import BlockValue
        from sugar_lift_py_tests.floor.return_value import ReturnValue
        from sugar_lift_py_tests.outcome import Incomplete
        from sugar_lift_py_tests.outcome.exit_set import (
            Completed,
            ExitSet,
            Halted,
        )
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            _ReducedBlock,
            reduce_block_to_exitset,
            reduce_statements,
        )

        del ctx

        body_entries, body_falls, body_ft = reduce_statements(self.body)
        body_entries = tuple(body_entries)

        routed_entries: tuple | None = None
        routed_falls = True
        for matcher, handler_body, slot_id in self.handlers:
            arm = route_except(
                body_entries, matcher, slot_id=slot_id, site=self.site
            )
            if arm is None:
                continue
            handler_entries, handler_falls, _ = reduce_statements(handler_body)
            routed_entries = (*arm.entries, *handler_entries)
            routed_falls = handler_falls
            break

        if routed_entries is None:
            if _first_effect_of_kind(body_entries, "raise") is None:
                else_entries, else_falls, _ = reduce_statements(self.orelse)
                routed_entries = (*body_entries, *else_entries)
                routed_falls = else_falls if self.orelse else body_falls
            else:
                routed_entries = body_entries
                routed_falls = body_falls

        pre_finally = _linear_entries_to_exitset(routed_entries, routed_falls)

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


def _linear_entries_to_exitset(entries: tuple, can_fall_through: bool) -> ExitSet:
    """Project the linear entry list into a one-or-few-exit ExitSet."""
    from sugar_lift_py_tests.outcome import Incomplete
    from sugar_lift_py_tests.outcome.exit_set import ExitSet
    from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock

    state = _ReducedBlock(
        entries=entries,
        can_fall_through=can_fall_through,
        fall_through=(),
    )
    # First hard halt Incomplete (raise) becomes Halted; testimony rides on state.
    for entry in entries:
        if not isinstance(entry, Incomplete):
            continue
        follow = entry.follow()
        if not follow.continues:
            return ExitSet.halted(entry.effect)
    return ExitSet.completed(state)


def _exitset_to_outcome(exits: ExitSet) -> Outcome:
    """Collapse ExitSet to the linear Complete(BlockValue) / Incomplete view."""
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.floor.return_value import ReturnValue
    from sugar_lift_py_tests.outcome import Incomplete
    from sugar_lift_py_tests.outcome.exit_set import Completed, Halted
    from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock

    from sugar_lift_py_tests.outcome import Complete as OutcomeComplete

    collapsed = exits.collapse()
    if isinstance(collapsed, Incomplete):
        # Pure halt: still expose as BlockValue red testimony so later
        # statements / invs see the effect entry (and finally supersede is
        # already applied).
        return Complete(
            BlockValue((collapsed,), can_fall_through=False)
        )
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

    # Multi-exit: flatten every exit's contribution under its guard.
    # For the linear BlockValue consumers, concatenate completed entries and
    # include each halt as Incomplete (guarded when possible).
    entries: list = []
    can_fall = False
    for exit_ in exits.normalize().exits:
        if isinstance(exit_, Halted):
            inc = Incomplete(exit_.effect)
            if exit_.guard is not None:
                # Preserve branch condition when non-trivial.
                from sugar_lift_py_tests.outcome.exit_set import true_guard

                if exit_.guard != true_guard():
                    inc = Incomplete(
                        exit_.effect, branch_conditions=(exit_.guard,)
                    )
            entries.append(inc)
        elif isinstance(exit_, Completed):
            value = exit_.value
            if isinstance(value, _ReducedBlock):
                entries.extend(value.entries)
                can_fall = can_fall or value.can_fall_through
            elif isinstance(value, ReturnValue):
                entries.append(value)
    return Complete(
        BlockValue(tuple(entries), can_fall_through=can_fall)
    )
