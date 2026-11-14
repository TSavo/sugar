"""Sugar for a closed import-bound Attribute chain."""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_python_source.canonical import cid_of_json
from sugar_lift_py_tests.outcome import ExitSet, Outcome
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar



def _seated_language_owned_floor(sugar: ImportMemberSugar):
    """Return the Cut 2 floor hung on this receipt's use site, if any."""
    from sugar_lift_py_tests.context_manager_resolution import (
        SourceFragmentCoordinateV1,
    )
    from sugar_lift_py_tests.floor.floor_value import FloorValue

    receipt = sugar.receipt
    site = receipt.use.get("useSite") or {}
    unit = getattr(sugar.site, "unit", None)
    context = getattr(unit, "construction_context", None) if unit is not None else None
    if context is None:
        return None
    resolutions = getattr(context, "source_import_value_resolutions", None)
    if not resolutions:
        return None
    source_cid = site.get("sourceCid") or getattr(receipt, "source_cid", None)
    try:
        coordinate = SourceFragmentCoordinateV1(
            source_cid,
            site["startLine"],
            site["startCol"],
            site["endLine"],
            site["endCol"],
        )
    except (KeyError, TypeError, ValueError):
        return None
    floored = resolutions.get(coordinate)
    if isinstance(floored, FloorValue):
        return floored
    return None


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
        floored = _seated_language_owned_floor(self)
        if floored is not None:
            return ExitSet.completed(floored)
        from sugar_lift_py_tests.floor.import_member_value import (
            _mint_import_member_value,
        )

        value = _mint_import_member_value(self.receipt)
        if value.qualified_name != self.qualified_name:
            raise ValueError("ImportMemberSugar receipt target mismatch")
        return ExitSet.completed(value)

    def to_term(self, *, owner: str):
        floored = _seated_language_owned_floor(self)
        if floored is not None:
            return floored.to_term(owner=owner)
        from sugar_lift_py_tests.floor.import_member_value import (
            _mint_import_member_value,
        )

        return _mint_import_member_value(self.receipt).to_term(owner=owner)
