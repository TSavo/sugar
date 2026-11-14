from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class PlaceAssignSugar(Sugar):
    receiver: Sugar
    selector_kind: str
    selector: object
    value: Sugar
    site: object = field(compare=False)
    # Nothing binds before a halt of the receiver, the value or the
    # selector: its pre-halt record is the block's prefix.
    halts_at_statement_head: ClassVar[bool] = True

    @classmethod
    def witnesses(cls):
        from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing

        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="PlaceAssignValue",
            reason="authenticated place store mirrors the Python reference assignment",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        from sugar_lift_py_tests.floor.place_assign_value import PlaceAssignValue

        def with_receiver(receiver):
            if (
                self.selector_kind == "attribute"
                and hasattr(receiver, "authenticates_plain_attribute_store")
                and not receiver.authenticates_plain_attribute_store(self.selector)
            ):
                from sugar_source_tree.panic import SugarNotWritten

                raise SugarNotWritten(
                    blame=self.site,
                    owner="PlaceAssignSugar",
                    observed="source-authenticated property data descriptor",
                    requested="the descriptor's authenticated assignment behavior",
                    fix=(
                        "construct the property's setter before treating the write "
                        "as an instance-field store"
                    ),
                )

            def with_value(value):
                if self.selector_kind == "attribute":
                    selector = self.selector
                elif self.selector_kind == "subscript":
                    return self.selector.desugar(ctx).and_then(
                        lambda selector: ExitSet.completed(
                            PlaceAssignValue(receiver, "subscript", selector, value)
                        )
                    )
                else:
                    raise ValueError("typed place selector mismatch")
                return ExitSet.completed(
                    PlaceAssignValue(receiver, "attribute", selector, value)
                )

            return self.value.desugar(ctx).and_then(with_value)

        return self.receiver.desugar(ctx).and_then(with_receiver)
