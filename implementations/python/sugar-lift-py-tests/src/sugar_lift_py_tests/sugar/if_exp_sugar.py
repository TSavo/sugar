from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class IfExpSugar(Sugar, role=SugarRole.TERM):
    """`a if cond else b` as a TERM (not statement GuardedFaces).

    Literal True/False conditions fold to the chosen branch. Symbolic and
    predicate conditions remain a typed runtime boundary until this TERM owner
    can construct a guarded value without inventing a selected branch.
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

    # A term-level conditional with a runtime condition is not an uninterpreted
    # value. Python chooses exactly one arm after evaluating the condition. Until
    # that guarded value is constructed here, preserve the typed runtime boundary
    # so descendants propagate it instead of minting coordinates about a value
    # that has not been selected.
    del true_v, false_v
    from sugar_lift_py_tests.effect import (
        ConditionalExpressionRuntimeEffect,
        RuntimeEffectWitness,
    )
    from sugar_lift_py_tests.ir import ctor

    condition = cond.to_term(owner="IfExpSugar runtime condition")

    return Incomplete(
        ConditionalExpressionRuntimeEffect(
            "conditional expression runtime boundary: Python evaluates the "
            "condition at runtime before choosing a branch; keep as typed red "
            f"until IfExpSugar constructs the guarded value. blame={site}",
            witness=RuntimeEffectWitness(
                operation=ctor("py.ifexp.select", [condition]),
                operand=condition,
                locus=str(site),
            ),
        )
    )
