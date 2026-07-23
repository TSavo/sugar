from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.effect import NameErrorEffect
from sugar_lift_py_tests.floor.branch_result_coordinate import branch_result_guard
from sugar_lift_py_tests.ir import not_
from sugar_lift_py_tests.outcome import ExitSet, Outcome, outcome_to_exitset
from sugar_lift_py_tests.sugar.binding_projection import (
    GuardedProjection,
    LoopCompletedFacesProjection,
    UnboundProjection,
)
from sugar_lift_py_tests.sugar.sugar_base import Sugar


def read_binding(state, *, read_name: str, read_site, ctx) -> ExitSet:
    if isinstance(state, Sugar):
        return outcome_to_exitset(state.desugar(ctx))
    if isinstance(state, UnboundProjection):
        return ExitSet.halted(NameErrorEffect(name=read_name, site=read_site))
    if isinstance(state, LoopCompletedFacesProjection):
        from sugar_lift_py_tests.ir import atomic, str_const

        exits = None
        for face in state.completed_faces:
            guard = atomic(
                "python.loop.completed-face",
                [
                    str_const(state.target_cid),
                    str_const(face.completion_kind),
                    str_const(face.guard_formula_cid),
                ],
            )
            projected = read_binding(
                face.state,
                read_name=read_name,
                read_site=read_site,
                ctx=ctx,
            ).guarded(guard)
            exits = projected if exits is None else exits.union(projected)
        if exits is None:
            raise TypeError("loop binding projection has no completed faces")
        return exits
    if not isinstance(state, GuardedProjection):
        raise TypeError(type(state))

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
