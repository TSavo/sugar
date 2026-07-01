from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import ArrayLiteral, BuilderState
from sugar_lift_py_tests.outcome import Complete, Outcome, complete_value
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class BuilderCtorSugar(Sugar, role=SugarRole.TERM, comes_before=("CallSugar",)):
    items: SugarBody
    blame: str

    @classmethod
    def owns(cls, site) -> bool:
        return _is_builder_call(site)

    @classmethod
    def build(cls, site, ctx) -> "BuilderCtorSugar":
        sugar = cls.from_site(
            site,
            items=ctx.build_body(site.call_args()[0], SugarRole.TERM),
        )
        if sugar is None:
            raise TypeError("BuilderCtorSugar claim built a non-builder call")
        return sugar

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


from sugar_lift_py_tests.sugar.sugar_base import registered_claims as _rc  # noqa: E402

BUILDER_CTOR_CLAIM = next(c for c in _rc() if c.name == "BuilderCtorSugar")
