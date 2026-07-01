from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import BlockValue, BoundVar
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.tuple_unpack_projection import TupleUnpackProjection
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class TupleAssignSugar(Sugar, role=SugarRole.STATEMENT):
    names: tuple[str, ...]
    receiver: SugarBody
    blame: str

    def __post_init__(self) -> None:
        if not isinstance(self.receiver, SugarBody):
            raise TypeError("TupleAssignSugar receiver must be factory-built")

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "Assign":
            return False
        targets = site.assign_targets()
        if len(targets) != 1 or targets[0].observed != "Tuple":
            return False
        value = site.assign_value()
        if value.observed != "Tuple":
            return False
        target_items = targets[0].terms()
        value_items = value.terms()
        return len(target_items) == len(value_items) and all(
            item.observed == "Name" for item in target_items
        )

    @classmethod
    def build(cls, site, ctx) -> "TupleAssignSugar":
        target_items = site.assign_targets()[0].terms()
        return cls(
            names=tuple(item.name_id() for item in target_items),
            receiver=ctx.build_body(site.assign_value(), SugarRole.TERM),
            blame=site.blame,
        )

    def desugar(self, ctx) -> Outcome:
        return Complete(
            BlockValue(
                tuple(
                    BoundVar(
                        name,
                        SugarBody(
                            TupleUnpackProjection(
                                self.receiver,
                                index,
                                blame=self.blame,
                            ),
                            SugarRole.TERM,
                        ),
                        scope=ctx,
                    )
                    for index, name in enumerate(self.names)
                )
            )
        )
