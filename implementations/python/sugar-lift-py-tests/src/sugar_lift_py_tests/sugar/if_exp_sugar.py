from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class IfExpSugar(Sugar, role=SugarRole.TERM):
    """`a if cond else b` as a TERM (not statement GuardedFaces).

    Literal True/False conditions fold to the chosen branch. Symbolic /
    predicate conditions become a ``py.if_exp`` coordinate over the three
    projected terms — never invent a branch, never force CallSiteValue under
    statement-style guards (TERM if-exp is not an if-statement record).
    """

    condition: SugarBody
    true_branch: SugarBody
    false_branch: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "IfExp"

    @classmethod
    def new(cls, site, ctx) -> "IfExpSugar":
        return cls(
            condition=ctx.build_body(site.ifexp_test(), SugarRole.TERM),
            true_branch=ctx.build_body(site.ifexp_body(), SugarRole.TERM),
            false_branch=ctx.build_body(site.ifexp_orelse(), SugarRole.TERM),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        return _call_pair(
            name="if_exp_literal_condition_return",
            owner_sugar="IfExpSugar",
            truthful=(
                "def A():\n"
                "    return 1 if True else 2\n"
                "\n"
                "def test_a():\n"
                "    assert A() == 1\n"
            ),
            lying=(
                "def A():\n"
                "    return 1 if True else 2\n"
                "\n"
                "def test_a():\n"
                "    assert A() == 2\n"
            ),
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return self.condition.reduce(ctx).and_then(
            lambda cond: self.true_branch.reduce(ctx).and_then(
                lambda true_v: self.false_branch.reduce(ctx).and_then(
                    lambda false_v: _if_exp_join(cond, true_v, false_v, self.site)
                )
            )
        )

    def walk_children(self):
        return (self.condition, self.true_branch, self.false_branch)


def _if_exp_join(cond, true_v, false_v, site) -> Outcome:
    from sugar_lift_py_tests.floor import CallSiteValue
    from sugar_lift_py_tests.ir import ctor
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
        FalseBoolLiteralSugar,
    )
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
        TrueBoolLiteralSugar,
    )

    if type(cond) is TrueBoolLiteralSugar:
        return Complete(true_v)
    if type(cond) is FalseBoolLiteralSugar:
        return Complete(false_v)

    # Symbolic / predicate / callsite condition: py.if_exp coordinate.
    def _term(v):
        if hasattr(v, "to_term"):
            return v.to_term(owner=str(site))
        if hasattr(v, "formula"):
            return v.formula
        from sugar_lift_py_tests.factory.factory_gap import factory_panic
        from sugar_lift_py_tests.factory.factory_gap_info import (
            FactoryGapInfo,
            GapKind,
            GapLocus,
        )
        from sugar_lift_py_tests.factory.factory_audit_row import FactoryAuditRow

        info = FactoryGapInfo(
            owner="IfExpSugar",
            blame=str(site),
            observed=type(v).__name__,
            requested="to_term for if_exp arm",
            fix="project arm to FOL",
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )
        factory_panic(
            info,
            FactoryAuditRow(
                role="if_exp",
                status="floor-gap",
                observed=type(v).__name__,
                blame=str(site),
                selected=None,
                candidates=[],
                message=info.message,
            ),
        )

    cond_term = _term(cond)
    return Complete(
        CallSiteValue(
            target_name="if_exp",
            arg_values=(cond, true_v, false_v)
            if all(hasattr(x, "to_term") or hasattr(x, "formula") for x in (cond, true_v, false_v))
            else (),
            parameters=(),
            term=ctor(
                "py.if_exp",
                [cond_term, _term(true_v), _term(false_v)],
            ),
            body=None,
            site=site,
        )
    )
