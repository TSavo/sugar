from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Incomplete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class AttributeDeleteEffectSugar(Sugar):
    receiver: Sugar
    attr: str
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.effect import (
            AttributeDeleteRuntimeEffect,
            runtime_effect_evidence,
        )
        from sugar_lift_py_tests.ir import ctor, str_const

        def delete(receiver):
            operand = ctor(
                "python:attribute_delete_target",
                [receiver.to_term(owner="attribute delete"), str_const(self.attr)],
            )
            return Incomplete(
                AttributeDeleteRuntimeEffect(
                    "attribute deletion runtime boundary: Python dispatches "
                    f"__delattr__/descriptor deletion for .{self.attr}",
                    **runtime_effect_evidence("py.delattr", operand, self.site),
                )
            )

        return self.receiver.desugar(ctx).and_then(delete)


@dataclass(frozen=True)
class SubscriptDeleteEffectSugar(Sugar):
    receiver: Sugar
    index: Sugar
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.effect import (
            SubscriptDeleteRuntimeEffect,
            runtime_effect_evidence,
        )
        from sugar_lift_py_tests.ir import ctor

        return self.receiver.desugar(ctx).and_then(
            lambda receiver: self.index.desugar(ctx).and_then(
                lambda index: self._delete(receiver, index, runtime_effect_evidence, ctor)
            )
        )

    def _delete(self, receiver, index, evidence, make_ctor):
        operand = make_ctor(
            "python:subscript_delete_target",
            [
                receiver.to_term(owner="subscript delete receiver"),
                index.to_term(owner="subscript delete index"),
            ],
        )
        from sugar_lift_py_tests.effect import SubscriptDeleteRuntimeEffect

        return Incomplete(
            SubscriptDeleteRuntimeEffect(
                "subscript deletion runtime boundary: Python dispatches __delitem__",
                **evidence("py.delitem", operand, self.site),
            )
        )
