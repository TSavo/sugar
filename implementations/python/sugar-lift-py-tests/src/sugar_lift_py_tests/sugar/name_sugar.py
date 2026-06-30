from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarClaim, SugarRole
from sugar_lift_py_tests.floor import BoundVar
from sugar_lift_py_tests.outcome import Complete, Outcome


@dataclass(frozen=True)
class NameSugar:
    identifier: str
    blame: str

    @classmethod
    def from_site(cls, site, _ctx) -> "NameSugar | None":
        if site.observed != "Name":
            return None
        return cls(identifier=site.name_id(), blame=site.blame)

    def desugar(self, ctx) -> Outcome:
        value = ctx.temporal.value_for(self.identifier)
        if isinstance(value, BoundVar):
            # the name aliases an expression -- recompose the source so the reference
            # IS that expression (reached through the alias).
            return value.source.reduce(ctx)
        return Complete(value)


def _owns(site) -> bool:
    return site.observed == "Name"


def _build(site, ctx) -> NameSugar:
    sugar = NameSugar.from_site(site, ctx)
    if sugar is None:
        raise TypeError("NameSugar claim built a non-name")
    return sugar


NAME_CLAIM = SugarClaim(
    name="NameSugar",
    role=SugarRole.TERM,
    owns=_owns,
    build=_build,
)
