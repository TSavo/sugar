from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.effect import NameErrorEffect
from sugar_lift_py_tests.floor.branch_result_coordinate import branch_result_guard
from sugar_lift_py_tests.ir import not_
from sugar_lift_py_tests.outcome import ExitSet, Outcome, outcome_to_exitset
from sugar_lift_py_tests.sugar.binding_projection import (
    GuardedProjection,
    LoopGuardedProjection,
    UnboundProjection,
)
from sugar_lift_py_tests.sugar.sugar_base import Sugar


def read_binding(state, *, read_name: str, read_site, ctx) -> ExitSet:
    if isinstance(state, Sugar):
        return outcome_to_exitset(state.desugar(ctx))
    if isinstance(state, UnboundProjection):
        return ExitSet.halted(NameErrorEffect(name=read_name, site=read_site))
    if isinstance(state, LoopGuardedProjection):
        exits = ExitSet(())
        for face in state.completed_faces:
            exits = exits.union(
                read_binding(
                    face.state,
                    read_name=read_name,
                    read_site=read_site,
                    ctx=ctx,
                ).guarded(face.guard_formula)
            )
        return exits.normalize()
    if not isinstance(state, GuardedProjection):
        from sugar_lift_py_tests.sugar.delete_name_sugar import _unhandled_projection

        _unhandled_projection(state, verb="read", name=read_name, site=read_site)

    guard = branch_result_guard(state.slot, read_site)
    return (
        read_binding(
            state.when_true,
            read_name=read_name,
            read_site=read_site,
            ctx=ctx,
        )
        .guarded(guard)
        .union(
            read_binding(
                state.when_false,
                read_name=read_name,
                read_site=read_site,
                ctx=ctx,
            ).guarded(not_(guard))
        )
    )


@dataclass(frozen=True)
class GuardedBindingReadSugar(Sugar):
    name: str
    state: object
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx: object = None) -> Outcome:
        return read_binding(
            self.state, read_name=self.name, read_site=self.site, ctx=ctx
        ).collapse()
