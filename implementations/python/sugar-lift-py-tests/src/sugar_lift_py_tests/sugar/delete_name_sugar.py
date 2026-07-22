from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.effect import NameErrorEffect
from sugar_lift_py_tests.floor.block_value import BlockValue
from sugar_lift_py_tests.floor.branch_result_coordinate import branch_result_guard
from sugar_lift_py_tests.ir import not_
from sugar_lift_py_tests.outcome import Complete, ExitSet, Outcome, outcome_to_exitset
from sugar_lift_py_tests.sugar.binding_projection import (
    GuardedProjection,
    UnboundProjection,
)
from sugar_lift_py_tests.sugar.sugar_base import Sugar


def delete_binding(state, *, name: str, site, ctx) -> ExitSet:
    if isinstance(state, Sugar):
        return ExitSet.completed(BlockValue((), can_fall_through=True))
    if isinstance(state, UnboundProjection):
        return ExitSet.halted(NameErrorEffect(name=name, site=site))
    if not isinstance(state, GuardedProjection):
        raise TypeError(type(state))
    guard = branch_result_guard(state.slot, site)
    return (
        delete_binding(state.when_true, name=name, site=site, ctx=ctx)
        .guarded(guard)
        .union(
            delete_binding(state.when_false, name=name, site=site, ctx=ctx).guarded(
                not_(guard)
            )
        )
    )


@dataclass(frozen=True)
class DeleteNameSugar(Sugar):
    name: str
    prior: object
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx: object = None) -> Outcome:
        return delete_binding(
            self.prior, name=self.name, site=self.site, ctx=ctx
        ).collapse()
