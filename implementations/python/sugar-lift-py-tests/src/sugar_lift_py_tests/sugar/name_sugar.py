from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import BoundVar
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witness_examples import name_return_witness
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class NameSugar(Sugar, role=SugarRole.TERM):
    identifier: str
    blame: str

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "Name"

    @classmethod
    def build(cls, site, ctx) -> "NameSugar":
        sugar = cls._from_site(site, ctx)
        if sugar is None:
            raise TypeError("NameSugar claim built a non-name")
        return sugar

    @classmethod
    def witnesses(cls):
        return name_return_witness()

    @classmethod
    def _from_site(cls, site, ctx) -> "NameSugar | None":
        if site.observed != "Name":
            return None
        return cls(identifier=site.name_id(), blame=site.blame)

    # Keep the old from_site signature for any callers that pass ctx.
    @classmethod
    def from_site(cls, site, _ctx) -> "NameSugar | None":
        return cls._from_site(site, _ctx)

    def _build(self, ctx) -> Outcome:
        outcome = ctx.temporal.value_outcome_for(self.identifier)
        if isinstance(outcome, Incomplete):
            return outcome
        value = outcome.value
        if isinstance(value, BoundVar):
            # The name aliases an expression -- recompose the source so the reference IS
            # that expression. Recompose against the binding's DEFINITION scope (where
            # the name still holds its old value), so `x = x + 1` reads the old x and
            # terminates instead of recomposing against itself.
            if not isinstance(value.source, SugarBody):
                raise TypeError("BoundVar source must be a composed SugarBody")
            return value.source.reduce(value.scope if value.scope is not None else ctx)
        return Complete(value)


from sugar_lift_py_tests.sugar.sugar_base import registered_claims as _rc  # noqa: E402

NAME_CLAIM = next(c for c in _rc() if c.name == "NameSugar")
