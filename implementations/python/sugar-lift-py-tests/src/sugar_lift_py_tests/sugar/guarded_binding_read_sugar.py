from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.effect import NameErrorEffect
from sugar_lift_py_tests.ir import not_
from sugar_lift_py_tests.outcome import ExitSet, Outcome, outcome_to_exitset
from sugar_lift_py_tests.sugar.if_sugar import predicate_formula
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_source_tree.binding_state import GuardedBinding, UnboundBinding
from sugar_source_tree.nodes import Node


def read_binding(state, *, read_name: str, read_site, ctx) -> ExitSet:
    if isinstance(state, Node):
        return outcome_to_exitset(state.sugar().desugar(ctx))
    if isinstance(state, UnboundBinding):
        return ExitSet.halted(NameErrorEffect(name=read_name, site=read_site))
    if not isinstance(state, GuardedBinding):
        raise TypeError(type(state))

    return outcome_to_exitset(state.test.sugar().desugar(ctx)).and_then(
        lambda guard_value: read_binding(
            state.when_true,
            read_name=read_name,
            read_site=read_site,
            ctx=ctx,
        )
        .guarded(predicate_formula(guard_value, read_site))
        .union(
            read_binding(
                state.when_false,
                read_name=read_name,
                read_site=read_site,
                ctx=ctx,
            ).guarded(not_(predicate_formula(guard_value, read_site)))
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
