from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.floor import ObjectField, ObjectValue
from sugar_lift_py_tests.outcome import Complete, Outcome, complete_value
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class ConstructorStrategy:
    class_name: str
    fields: tuple[tuple[str, SugarBody], ...]

    def __post_init__(self) -> None:
        for _name, body in self.fields:
            if not isinstance(body, SugarBody):
                raise TypeError("ConstructorStrategy fields must be factory-built")

    def emit(self, sugar, ctx) -> Outcome:
        del sugar
        return Complete(
            ObjectValue(
                class_name=self.class_name,
                fields=tuple(
                    ObjectField(
                        name=name,
                        value=complete_value(
                            body.reduce(ctx),
                            owner=f"{self.class_name}.{name}",
                        ),
                    )
                    for name, body in self.fields
                ),
            )
        )
