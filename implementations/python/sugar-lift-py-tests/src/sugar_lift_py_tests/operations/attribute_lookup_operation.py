from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.factory import FactoryAuditRow, FactoryGap, FactoryGapInfo
from sugar_lift_py_tests.floor import ObjectValue, StringValue
from sugar_lift_py_tests.outcome import Complete, Outcome


@dataclass(frozen=True)
class AttributeLookupOperation:
    name: str
    owner: str = "AttributeSugar"
    blame: str = "<unknown>"

    def attribute_object(self, receiver: ObjectValue, ctx: object) -> Outcome:
        del ctx
        for field in reversed(receiver.fields):
            if field.name == self.name:
                return Complete(field.value)
        for method in reversed(receiver.methods):
            if method.name == self.name:
                return self._floor_gap(
                    observed=f"{receiver.class_name}.{self.name}",
                    requested="bound method attribute floor",
                    fix=(
                        f"add bound-method attribute floor for "
                        f"`{receiver.class_name}.{self.name}`"
                    ),
                )
        try:
            return receiver.call_method_value(
                "__getattr__",
                (StringValue(self.name),),
                owner=self.owner,
                blame=self.blame,
            )
        except FactoryGap as gap:
            if _gap_requested(gap) != "constructor-bound method":
                raise
            return self._floor_gap(
                observed=f"{receiver.class_name}.{self.name}",
                requested="constructor-bound field",
                fix=(
                    f"bind `self.{self.name}` in `{receiver.class_name}.__init__`, "
                    f"define `__getattr__` on `{receiver.class_name}`, "
                    "or add the floor that owns this attribute"
                ),
            )

    def _floor_gap(self, *, observed: str, requested: str, fix: str) -> None:
        info = FactoryGapInfo(
            owner=self.owner,
            blame=self.blame,
            observed=observed,
            requested=requested,
            fix=fix,
            gap_kind="Floor",
            gap_locus="construction",
        )
        raise FactoryGap(
            info,
            FactoryAuditRow(
                role=requested,
                status="floor-gap",
                observed=observed,
                blame=self.blame,
                selected=None,
                candidates=[],
                message=info.message,
            ),
        )


def _gap_requested(gap: FactoryGap) -> str | None:
    info = gap.info
    if isinstance(info, dict):
        return info.get("requested")
    return getattr(info, "requested", None)
