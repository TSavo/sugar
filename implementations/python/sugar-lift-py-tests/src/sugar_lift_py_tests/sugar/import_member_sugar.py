"""Sugar for a closed import-bound Attribute chain."""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar


@dataclass(frozen=True)
class ImportMemberSugar(ConstructedTermSugar):
    """``import M as h; h.a.b`` as the closed coordinate ``M.a.b``."""

    qualified_name: str
    receipt: object = dataclass_field(compare=False, repr=False)
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
        from sugar_lift_py_tests.floor.import_member_value import (
            _mint_import_member_value,
        )

        value = _mint_import_member_value(self.receipt)
        if value.qualified_name != self.qualified_name:
            raise ValueError("ImportMemberSugar receipt target mismatch")
        return Complete(value)

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.floor.import_member_value import (
            _mint_import_member_value,
        )

        return _mint_import_member_value(self.receipt).to_term(owner=owner)
