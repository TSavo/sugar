from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.sugar.sugar_base import (
    ConstructedTermSugar,
    require_constructed_term_sugar,
)


@dataclass(frozen=True)
class ReceiverFieldStoreStateSugar(ConstructedTermSugar):
    receiver: ConstructedTermSugar
    value: ConstructedTermSugar
    attr: str
    site: object = field(compare=False)

    @classmethod
    def witnesses(cls):
        return ()

    def __post_init__(self):
        require_constructed_term_sugar(
            self.receiver, owner="ReceiverFieldStoreStateSugar.receiver"
        )
        require_constructed_term_sugar(
            self.value, owner="ReceiverFieldStoreStateSugar.value"
        )

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:receiver-field-store-state",
            (
                self.occurrence_term(owner=owner),
                self.receiver.to_term(owner=owner),
                str_const(self.attr),
                self.value.to_term(owner=owner),
            ),
            symbol_kind="coordinate",
        )

    def desugar(self, ctx=None):
        from sugar_lift_py_tests.floor.object_value import ObjectValue
        from sugar_lift_py_tests.gap.panic import construction_panic_gap
        from sugar_lift_py_tests.outcome import Complete

        def update(receiver, value):
            if not isinstance(receiver, ObjectValue):
                construction_panic_gap(
                    owner="ReceiverFieldStoreStateSugar",
                    blame=self.site,
                    observed=type(receiver).__name__,
                    requested="authenticated source receiver",
                    fix="retain field mutation as typed loud until its receiver floors",
                )
            return Complete(receiver.with_field_store(self.attr, value))

        return self.receiver.desugar(ctx).and_then(
            lambda receiver: self.value.desugar(ctx).and_then(
                lambda value: update(receiver, value)
            )
        )
