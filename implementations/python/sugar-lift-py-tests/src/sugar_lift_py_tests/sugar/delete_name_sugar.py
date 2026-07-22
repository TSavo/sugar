from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.effect import NameErrorEffect
from sugar_lift_py_tests.floor.block_value import BlockValue
from sugar_lift_py_tests.ir import not_
from sugar_lift_py_tests.outcome import Complete, ExitSet, Outcome, outcome_to_exitset
from sugar_lift_py_tests.sugar.if_sugar import predicate_formula
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_source_tree.binding_state import GuardedBinding, UnboundBinding
from sugar_source_tree.nodes import Node


def delete_binding(state, *, name: str, site, ctx) -> ExitSet:
    if isinstance(state, Node):
        return ExitSet.completed(BlockValue((), can_fall_through=True))
    if isinstance(state, UnboundBinding):
        return ExitSet.halted(NameErrorEffect(name=name, site=site))
    if not isinstance(state, GuardedBinding):
        raise TypeError(type(state))
    return outcome_to_exitset(state.test.sugar().desugar(ctx)).and_then(
        lambda guard_value: delete_binding(
            state.when_true, name=name, site=site, ctx=ctx
        )
        .guarded(predicate_formula(guard_value, site))
        .union(
            delete_binding(state.when_false, name=name, site=site, ctx=ctx).guarded(
                not_(predicate_formula(guard_value, site))
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
