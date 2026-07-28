"""Sugar for a closed import-bound Attribute chain."""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class ImportMemberSugar(Sugar):
    """``import M as h; h.a.b`` as the closed coordinate ``M.a.b``."""

    qualified_name: str
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing

        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="ImportMemberValue",
            reason="projects one import-bound export coordinate from lexical authority",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx
        from sugar_lift_py_tests.floor.import_member_value import ImportMemberValue

        return Complete(ImportMemberValue(self.qualified_name))
