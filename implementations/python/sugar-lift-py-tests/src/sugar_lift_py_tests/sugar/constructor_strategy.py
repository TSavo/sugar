from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.factory import FactoryAuditRow, FactoryGap, FactoryGapInfo
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
                fields=tuple(self._field(name, body, ctx) for name, body in self.fields),
            )
        )

    def _field(self, name: str, body: SugarBody, ctx) -> ObjectField:
        try:
            value = complete_value(
                body.reduce(ctx),
                owner=f"{self.class_name}.{name}",
            )
        except TypeError as exc:
            info = FactoryGapInfo(
                owner="python.factory",
                blame=f"{self.class_name}.{name}",
                observed=type(exc).__name__,
                requested="constructor field floor",
                fix=f"write more constructor floor for `{self.class_name}.{name}`: {exc}",
                gap_kind="Floor",
                gap_locus="construction",
            )
            raise FactoryGap(
                info,
                FactoryAuditRow(
                    role="constructor field floor",
                    status="floor-gap",
                    observed=info.observed,
                    blame=info.blame,
                    selected=None,
                    candidates=[],
                    message=info.message,
                ),
            ) from exc
        return ObjectField(name=name, value=value)
