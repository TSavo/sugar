"""Sugar for a closed import-bound Attribute chain."""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar


@dataclass(frozen=True)
class ImportMemberSugar(ConstructedTermSugar):
    """``import M as h; h.a.b`` as the closed coordinate ``M.a.b``."""

    authenticated_use: object
    site: object = dataclass_field(compare=False)

    def __post_init__(self) -> None:
        from sugar_lift_py_tests.import_binding import AuthenticatedImportUseV1
        from sugar_source_tree.panic import BackendDefect

        if type(self.authenticated_use) is not AuthenticatedImportUseV1:
            raise BackendDefect(
                owner="ImportMemberSugar",
                blame=self.site,
                observed=type(self.authenticated_use).__name__,
                requested="exact AuthenticatedImportUseV1",
                fix="carry the lexical import-value receipt into member construction",
            )
        self.authenticated_use.revalidate()

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

        return Complete(ImportMemberValue._from_authenticated_use(self.authenticated_use))

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.floor.import_member_value import ImportMemberValue

        return ImportMemberValue._from_authenticated_use(
            self.authenticated_use
        ).to_term(owner=owner)
