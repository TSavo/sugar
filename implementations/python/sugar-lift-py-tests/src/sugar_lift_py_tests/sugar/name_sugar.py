from __future__ import annotations

import ast
from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarClaim, SugarRole
from sugar_lift_py_tests.outcome import Complete, Outcome


@dataclass(frozen=True)
class NameSugar:
    identifier: str
    blame: str

    @classmethod
    def from_site(cls, site, _ctx) -> "NameSugar | None":
        if not isinstance(site.node, ast.Name):
            return None
        return cls(identifier=site.node.id, blame=site.blame)

    def desugar(self, ctx) -> Outcome:
        return Complete(ctx.temporal.value_for(self.identifier))


def _owns(site) -> bool:
    return isinstance(site.node, ast.Name)


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
