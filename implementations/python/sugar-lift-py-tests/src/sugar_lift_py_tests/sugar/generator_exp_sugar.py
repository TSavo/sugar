from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import ComprehensionValue
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.comprehension_clauses import (
    build_clauses,
    clause_children,
    reduce_clauses,
    supports_clauses,
)
from sugar_lift_py_tests.sugar.list_comp_sugar import _floor_as_term
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class GeneratorExpSugar(Sugar, role=SugarRole.TERM):
    clauses: tuple
    elt_body: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "GeneratorExp" and supports_clauses(
            site.genexp_generators()
        )

    @classmethod
    def new(cls, site, ctx) -> "GeneratorExpSugar":
        return cls(
            clauses=build_clauses(site.genexp_generators(), ctx),
            elt_body=ctx.build_body(site.genexp_element(), SugarRole.TERM),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        prefix = "def A(z):\n    y = (x for x in z)\n    return 1\n\n"
        return _call_pair(
            name="generator_exp_return",
            owner_sugar="GeneratorExpSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 1\n",
            lying=prefix + "def test_a():\n    assert A(5) == 0\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.ir import ctor

        return reduce_clauses(
            self.clauses,
            ctx,
            lambda bound_ctx, generator_args: self.elt_body.reduce(
                bound_ctx
            ).and_then(
                lambda elt: Complete(
                    ComprehensionValue(
                        ctor(
                            "py.genexp",
                            [
                                _floor_as_term(elt, owner=str(self.site)),
                                *generator_args,
                            ],
                        )
                    )
                )
            ),
        )

    def walk_children(self):
        return (self.elt_body, *clause_children(self.clauses))
