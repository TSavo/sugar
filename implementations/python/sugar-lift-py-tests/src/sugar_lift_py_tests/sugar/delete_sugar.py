from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing


@dataclass(frozen=True)
class DeleteTarget:
    kind: str
    detail: str


@dataclass(frozen=True)
class DeleteSugar(Sugar):
    """Ordered lexical unbindings and typed Python store-delete effects."""

    targets: tuple[DeleteTarget, ...]
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        return NotVerdictBearing(
            sugar_name="DeleteSugar",
            floor_name="ScopeUnbind",
            reason="delete constructs scope/effect state rather than a value verdict",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx
        from sugar_lift_py_tests.effect import (
            AttributeDeleteRuntimeEffect,
            SubscriptDeleteRuntimeEffect,
            runtime_effect_evidence,
        )
        from sugar_lift_py_tests.floor.block_value import BlockValue
        from sugar_lift_py_tests.floor.scope_unbind import ScopeUnbind
        from sugar_lift_py_tests.ir import make_var

        entries = []
        for target in self.targets:
            if target.kind == "name":
                entries.append(ScopeUnbind((target.detail,)))
                continue
            if target.kind == "attribute":
                operand = make_var(f"delete_target.{target.detail}")
                effect = AttributeDeleteRuntimeEffect(
                    "attribute deletion runtime boundary: Python must dispatch "
                    f"__delattr__/descriptor deletion for .{target.detail}; "
                    f"site={self.site}",
                    **runtime_effect_evidence("py.delattr", operand, self.site),
                )
            else:
                operand = make_var(f"delete_target[{target.detail}]")
                effect = SubscriptDeleteRuntimeEffect(
                    "subscript deletion runtime boundary: Python must dispatch "
                    f"__delitem__ for [{target.detail}]; site={self.site}",
                    **runtime_effect_evidence("py.delitem", operand, self.site),
                )
            entries.append(Incomplete(effect))
        return Complete(BlockValue(tuple(entries), can_fall_through=True))
