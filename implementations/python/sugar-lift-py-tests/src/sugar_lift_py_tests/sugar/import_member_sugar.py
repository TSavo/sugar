"""Sugar for a closed import-bound Attribute chain."""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_python_source.canonical import cid_of_json
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar


@dataclass(frozen=True)
class ImportMemberSugar(ConstructedTermSugar):
    """``import M as h; h.a.b`` as the closed coordinate ``M.a.b``."""

    qualified_name: str
    receipt: object = dataclass_field(compare=False, repr=False)
    site: object = dataclass_field(compare=False)

    @property
    def preimage(self) -> dict[str, object]:
        """Closed testimony projected from the authenticated import receipt."""
        from sugar_lift_py_tests.floor.import_member_value import (
            _mint_import_member_value,
        )

        value = _mint_import_member_value(self.receipt)
        if value.qualified_name != self.qualified_name:
            raise ValueError("ImportMemberSugar receipt target mismatch")
        return {
            "kind": "python-import-member-sugar",
            "schemaVersion": "1",
            "qualifiedName": value.qualified_name,
            "sourceCid": value.source_cid,
            "importBindingCid": value.import_binding_cid,
            "useCid": value.use_cid,
            "exportedMemberPath": list(value.exported_member_path),
        }

    @property
    def cid(self) -> str:
        return cid_of_json(self.preimage)

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
