from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.effect import RuntimeEffect
from sugar_lift_py_tests.outcome import Incomplete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import SugarWitnessPair, WitnessSource
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class _LiteralIfExp:
    condition: bool
    true_branch: SugarBody
    false_branch: SugarBody


@dataclass(frozen=True)
class _RuntimeIfExp:
    reason: str


IfExpPlan = _LiteralIfExp | _RuntimeIfExp


@dataclass(frozen=True)
class IfExpSugar(Sugar, role=SugarRole.TERM):
    plan: IfExpPlan
    blame: str

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "IfExp"

    @classmethod
    def witnesses(cls) -> SugarWitnessPair:
        return SugarWitnessPair(
            name="if_exp_literal_condition_return",
            owner_sugar=cls.__name__,
            family="python-conditional-expression",
            truthful=WitnessSource(
                source=(
                    "def A():\n"
                    "    return 1 if True else 2\n"
                    "\n"
                    "def test_a():\n"
                    "    assert A() == 1\n"
                ),
                expected="sat",
            ),
            lying=WitnessSource(
                source=(
                    "def A():\n"
                    "    return 1 if True else 2\n"
                    "\n"
                    "def test_a():\n"
                    "    assert A() == 2\n"
                ),
                expected="unsat",
            ),
        )

    @classmethod
    def build(cls, site, ctx) -> "IfExpSugar":
        if not cls.owns(site):
            raise TypeError("IfExpSugar claim built a non-IfExp")
        test = site.ifexp_test()
        if test.observed != "PrimitiveLiteral" or not isinstance(
            test.literal_value(), bool
        ):
            return cls(
                plan=_RuntimeIfExp(
                    f"condition `{test.observed}` is evaluated at runtime"
                ),
                blame=site.blame,
            )
        return cls(
            plan=_LiteralIfExp(
                condition=test.literal_value(),
                true_branch=ctx.build_body(site.ifexp_body(), SugarRole.TERM),
                false_branch=ctx.build_body(site.ifexp_orelse(), SugarRole.TERM),
            ),
            blame=site.blame,
        )

    def desugar(self, ctx) -> Outcome:
        if isinstance(self.plan, _RuntimeIfExp):
            return _runtime_condition_effect(self.blame, self.plan.reason)
        branch = (
            self.plan.true_branch if self.plan.condition else self.plan.false_branch
        )
        return branch.reduce(ctx)


def _runtime_condition_effect(blame: str, reason: str) -> Incomplete:
    return Incomplete(
        RuntimeEffect(
            "conditional expression runtime boundary: "
            f"{reason}. Python evaluates the condition at runtime before "
            "choosing a branch; keep as typed red until a narrower "
            f"vendor-cited reduction owns the shape. blame={blame}"
        )
    )
