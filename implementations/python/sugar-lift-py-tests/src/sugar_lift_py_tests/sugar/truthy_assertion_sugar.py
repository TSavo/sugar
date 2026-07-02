from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory import FactoryGap
from sugar_lift_py_tests.floor import ObjectValue
from sugar_lift_py_tests.ir import Formula, Term, atomic
from sugar_lift_py_tests.outcome import Incomplete, complete_value
from sugar_lift_py_tests.sugar.object_truthiness import object_truth_formula
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.symbolic_term import can_symbolic_term, symbolic_term
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class TruthyAssertionSugar(Sugar, role=SugarRole.ASSERTION):
    source_role = "python.truthy-assertion-sugar"

    term: Term
    term_body: SugarBody | None
    degraded_reason: str | None
    blame: str

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "Assert":
            return False
        test = site.assert_test()
        if test.observed in {"Call", "Compare", "UnaryOp"}:
            return False
        return can_symbolic_term(test)

    @classmethod
    def build(cls, site, ctx) -> "TruthyAssertionSugar":
        term_body, degraded_reason = _projectable_truth_body(site, ctx)
        return cls(
            term=symbolic_term(
                site.assert_test(),
                owner="truthy assertion",
                import_aliases=getattr(ctx, "import_aliases", {}) or {},
                from_imports=getattr(ctx, "from_imports", {}) or {},
                name_resolver=getattr(ctx, "name_resolver", {}) or {},
                external_bridge_sink=getattr(ctx, "external_bridge_sink", None),
            ),
            term_body=term_body,
            degraded_reason=degraded_reason,
            blame=site.blame,
        )

    def assertion_formula(self) -> Formula:
        return atomic("py.truthy", [self.term])

    def desugar(self, ctx):
        if self.term_body is None:
            return self.assertion_formula()
        outcome = self.term_body.reduce(ctx)
        if isinstance(outcome, Incomplete):
            return outcome
        value = complete_value(outcome, owner="TruthyAssertionSugar term")
        if not isinstance(value, ObjectValue):
            return self.assertion_formula()
        return object_truth_formula(
            value,
            ctx,
            owner="TruthyAssertionSugar",
            blame=self.blame,
        )


def _projectable_truth_body(site, ctx) -> tuple[SugarBody | None, str | None]:
    try:
        return ctx.build_body(site.assert_test(), SugarRole.TERM), None
    except FactoryGap as gap:
        return None, _truthy_degraded_reason(gap)
    except TypeError as exc:
        return None, _truthy_type_degraded_reason(exc)


def _truthy_degraded_reason(gap: FactoryGap) -> str:
    return gap.info.get("fix", str(gap))


def _truthy_type_degraded_reason(exc: TypeError) -> str:
    return f"pre-build type error: {exc}"
