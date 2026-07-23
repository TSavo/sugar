from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.effect import GroupedRaiseEffect, RaiseEffect
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class GroupedRaiseSugar(Sugar):
    """Construct one authenticated exception-group tree without flattening it."""

    group_identity: str
    message: Sugar
    children: tuple[Sugar, ...]
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_source_tree.panic import SugarNotWritten

        message = self.message.desugar(ctx)
        if not isinstance(message, Complete):
            return message
        effects = []
        for child in self.children:
            outcome = child.desugar(ctx)
            if not isinstance(outcome, Incomplete) or not isinstance(
                outcome.effect, (RaiseEffect, GroupedRaiseEffect)
            ):
                raise SugarNotWritten(
                    owner="GroupedRaiseSugar.desugar",
                    observed=type(outcome).__name__,
                    requested="a constructed raise effect for every group child",
                    fix="keep non-exception group members loud",
                )
            effects.append(outcome.effect)
        occurrence = f"{self.site.filename}:{self.site.line}:{self.site.col}"
        return Incomplete(
            GroupedRaiseEffect(
                self.group_identity,
                message.value,
                tuple(effects),
                occurrence=occurrence,
            )
        )
