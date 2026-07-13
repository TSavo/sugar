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
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


def _floor_as_term(value, *, owner: str):
    return value.to_term(owner=owner)


@dataclass(frozen=True)
class ListCompSugar(Sugar, role=SugarRole.TERM):
    clauses: tuple
    elt_body: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "ListComp" and supports_clauses(
            site.listcomp_generators()
        )

    @classmethod
    def new(cls, site, ctx) -> "ListCompSugar":
        return cls(
            clauses=build_clauses(site.listcomp_generators(), ctx),
            elt_body=ctx.build_body(site.listcomp_element(), SugarRole.TERM),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        prefix = "def A(z):\n    y = [x for x in z]\n    return 1\n\n"
        return _call_pair(
            name="list_comp_return",
            owner_sugar="ListCompSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 1\n",
            lying=prefix + "def test_a():\n    assert A(5) == 0\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.ir import ctor

        return reduce_clauses(
            self.clauses,
            ctx,
            lambda bound_ctx, generator_args: self.elt_body.reduce(bound_ctx).and_then(
                lambda elt: Complete(
                    ComprehensionValue(
                        ctor(
                            "py.listcomp",
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
