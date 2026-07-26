from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.effect import Effect, effect_reason, require_effect


@dataclass(frozen=True)
class Incomplete:
    """A typed effect, plus any caller obligation already incurred on this path.

    ``pending_contracts`` is the effect face of the parameter-contract carrier
    (#6352). `o.x = p[k]` evaluates `p[k]` -- incurring `python:indexable(p)` --
    and THEN answers with a store effect. The obligation was incurred before
    the effect, on the path that reached it, so it is owed. It used to have
    nowhere to go and `rewrap_pending` panicked NAMED rather than drop it.

    It rides here for exactly the reason ``branch_conditions`` does: it is
    wrapper-level testimony ABOUT the outcome, never smashed into the effect,
    which stays pristine. And it goes on to the block record through
    ``contribution``, which is what enrols it for the linker to discharge.

    A PARTITION now has its own arm rather than being loud: every face of an
    ``ExitSet`` carries the obligation weakened under that face's own guard,
    on ``Completed.pending_contracts`` and ``Halted.pending_contracts`` alike.
    See ``floor/single_outcome_law.rewrap_pending``.
    """

    effect: Effect
    branch_conditions: tuple = ()
    pending_contracts: tuple = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "effect", require_effect(self.effect))

    @property
    def reason(self) -> str:
        base = effect_reason(self.effect)
        if not self.branch_conditions:
            return base
        conds = " and ".join(repr(f) for f in self.branch_conditions)
        return f"{base}; effect occurs under branch condition {conds}"

    def binary_conditional(
        self, then, else_body, ctx: object = None, site=None
    ) -> "Incomplete":
        # An effect never decides a branch; it rides straight through by returning
        # itself. Same shape for every operation an effect is asked to do.
        del then, else_body, ctx, site
        return self

    def follow(self):
        # Default: an effect halts the run; the rest of the block stays unreduced.
        #
        # A STORE is neither. `o.x = p` may complete (Python goes on to the next
        # statement, the target stays assigned) or may halt (`__setattr__` /
        # descriptor / `__setitem__` dispatch belongs to the runtime). Which one
        # is RUNTIME-SELECTED, so BOTH faces are kept: continues under `not g`,
        # halts under `g`, over the store's own authenticated occurrence
        # coordinate. See floor/store_outcome_coordinate.py.
        #
        # Modelling a store as unconditionally continuing (what this returned
        # before) claims assignment is infallible; modelling it as halting would
        # drop every later binding and fabricate a construction gap. The guarded
        # pair is the only spelling that states neither.
        from sugar_lift_py_tests.outcome.follow_step import FollowStep
        from sugar_lift_py_tests.floor.store_outcome_coordinate import (
            is_store_family_effect,
            store_halted_guard,
        )

        if is_store_family_effect(self.effect):
            return FollowStep.continue_with(halt_guard=store_halted_guard(self.effect))
        return FollowStep.halt(keeps_rest=True)

    def contribution(self):
        # An effect contributes itself to the block record; the unresolved tail rides
        # beside it via follow.
        #
        # Any obligation incurred BEFORE the effect contributes beside it, one
        # row per demand, exactly as a completed carrier would (#6352). The
        # entry's own `contribution` does the set-to-singleton split, so this
        # never has to know the set exists.
        return (
            self,
            *(
                row
                for entry in self.pending_contracts
                for row in entry.contribution()
            ),
        )

    def guarded(self, formula):
        """Keep a typed effect red while recording its branch condition.

        The condition is wrapper-level metadata, recorded on the Incomplete --
        NOT smashed into the effect's reason. The effect stays pristine (some
        effects, e.g. RaiseEffect, compute ``reason`` as a property with no field
        to replace), and a raise guarded by several nested ifs accumulates its
        conditions in order."""
        # A carried obligation weakens on the same face the effect is guarded
        # by: a caller that never takes the branch never evaluated `p[k]` and
        # owes nothing (#6352).
        return Incomplete(
            self.effect,
            (*self.branch_conditions, formula),
            tuple(entry.demanded_under(formula) for entry in self.pending_contracts),
        )

    def extend_scope(self, ctx):
        # An effect does not rebind: the rest never runs under a new scope.
        return ctx

    def inv_contribution(self):
        # An effect states no inv.
        return ()

    def post_contribution(self):
        # An effect posts no exit.
        return ()

    def mint_contribution(self, name, formals):
        # An effect mints no row.
        del name, formals
        return ()

    def edge_contribution(self, source_contract):
        # An effect projects no call edge.
        del source_contract
        return ()

    def and_then(self, step):
        # An effect never continues: it propagates by returning itself, the next step
        # never runs.
        del step
        return self


def _effect_continues_control_flow(effect) -> bool:
    """Retained name for the store family, now with the honest meaning: this
    effect has a completed face at all (as opposed to halting outright).

    It no longer means "this effect always continues" -- that claim was the
    defect. The store family owns the sole membership list, in
    floor/store_outcome_coordinate.py.
    """
    from sugar_lift_py_tests.floor.store_outcome_coordinate import (
        is_store_family_effect,
    )

    return is_store_family_effect(effect)
