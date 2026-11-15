"""Sugar for a closed import-bound Attribute chain."""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_python_source.canonical import cid_of_json
from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar


@dataclass(frozen=True)
class ImportMemberSugar(ConstructedTermSugar):
    """``import M as h; h.a.b`` as the closed coordinate ``M.a.b``.

    The dotted read is two-faced (it may raise where it is read); a name a
    ``from`` import bound is the one completed arm (``desugar``).
    """

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

    def desugar(self, ctx: object = None) -> ExitSet:
        """The read of the import-bound reference at ``site``.

        A dotted read (``np.nan``, ``pd.util.foo``: the use's own member path
        is not empty) runs ``getattr`` where it is read, which may raise, and
        the lifter holds no module's namespace: it is the two-faced undecided
        read (``ImportMemberValue.read_faces``), the reference under its
        completes atom and an undetermined raise under the complement, owing
        the ``undecided`` member under the import's target symbol.

        A name ``from m import x`` bound (the use's member path is empty; the
        path is the binding's) is read by name: the import statement already
        ran, nothing runs at the read, so it is the one completed arm.
        """
        del ctx
        from sugar_lift_py_tests.floor.import_member_value import (
            _mint_import_member_value,
        )

        value = _mint_import_member_value(self.receipt)
        if value.qualified_name != self.qualified_name:
            raise ValueError("ImportMemberSugar receipt target mismatch")
        if not self.receipt.use.get("exportedMemberPath"):
            return ExitSet.completed(value)
        return value.read_faces(self.site)

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.floor.import_member_value import (
            _mint_import_member_value,
        )

        return _mint_import_member_value(self.receipt).to_term(owner=owner)
