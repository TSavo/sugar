from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarClaim, SugarRole
from sugar_lift_py_tests.factory.sugar_constructors import build_builder_ctor_sugar
from sugar_lift_py_tests.floor import ArrayLiteral, BuilderState
from sugar_lift_py_tests.outcome import Complete, Outcome, complete_value
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class BuilderCtorSugar:
    items: SugarBody
    blame: str

    @classmethod
    def from_site(cls, site, *, items: SugarBody) -> "BuilderCtorSugar | None":
        if not _is_builder_call(site):
            return None
        if site.call_arg_count() != 1:
            return None
        return cls(
            items=items,
            blame=site.blame,
        )

    def desugar(self, ctx) -> Outcome:
        value = complete_value(self.items.reduce(ctx), owner="BuilderCtorSugar")
        if not isinstance(value, ArrayLiteral):
            raise TypeError("BuilderCtorSugar argument must reduce to ArrayLiteral")
        return Complete(BuilderState(value))


def _is_builder_call(site) -> bool:
    return (
        site.observed == "Call"
        and not site.call_is_method_call()
        and site.call_target_name() == "Builder"
    )


def _owns(site) -> bool:
    return _is_builder_call(site)


BUILDER_CTOR_CLAIM = SugarClaim(
    name="BuilderCtorSugar",
    role=SugarRole.TERM,
    owns=_owns,
    build=build_builder_ctor_sugar,
)
