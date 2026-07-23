from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field

from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class DynamicUnpackAssignSugar(Sugar):
    """Construct a valid unpack shape while keeping unknown iteration loud."""

    target_names: tuple[str, ...]
    value: Sugar
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing

        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="typed dynamic unpack obligation",
            reason="unknown iterable cardinality and members cannot fabricate bindings",
        )

    def desugar(self, ctx=None):
        del ctx
        from sugar_source_tree.panic import SugarNotWritten

        raise SugarNotWritten(
            owner="DynamicUnpackAssignSugar.desugar",
            observed="runtime-selected unpack members",
            requested="authenticated finite iterable members and cardinality",
            fix="construct the iterable members or keep the unpack obligation loud",
        )
