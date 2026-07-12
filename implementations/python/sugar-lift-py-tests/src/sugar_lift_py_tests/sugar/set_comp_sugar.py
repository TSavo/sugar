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
class SetCompSugar(Sugar, role=SugarRole.TERM):
    clauses: tuple
    elt_body: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "SetComp" and supports_clauses(
            site.setcomp_generators()
        )

    @classmethod
    def new(cls, site, ctx) -> "SetCompSugar":
        return cls(
            clauses=build_clauses(site.setcomp_generators(), ctx),
            elt_body=ctx.build_body(site.setcomp_element(), SugarRole.TERM),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        prefix = "def A(z):\n    y = {x for x in z}\n    return 1\n\n"
        return _call_pair(
            name="set_comp_return",
            owner_sugar="SetCompSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 1\n",
            lying=prefix + "def test_a():\n    assert A(5) == 0\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        clause = self.clauses[0]
        if (
            len(self.clauses) == 1
            and len(clause.bindings) == 1
            and clause.bindings[0][1] == ()
            and not clause.conditions
        ):
            return clause.iterable.reduce(ctx).and_then(
                lambda iterable: self._finite_or_coordinate(iterable, ctx)
            )
        return self._coordinate(ctx)

    def _finite_or_coordinate(self, iterable, ctx):
        from sugar_lift_py_tests.floor import ListValue, TupleValue

        if isinstance(iterable, (ListValue, TupleValue)):
            return self._collect_finite(iterable.elements, (), ctx)
        return self._coordinate(ctx, iterable)

    def _collect_finite(self, remaining, accumulated, ctx):
        from sugar_lift_py_tests.floor import ScopeRebind, SetValue

        if not remaining:
            return Complete(SetValue(accumulated))
        item, *rest = remaining
        name = self.clauses[0].bindings[0][0]
        item_ctx = ScopeRebind(name, item).extend_scope(ctx)
        return self.elt_body.reduce(item_ctx).and_then(
            lambda value: self._collect_finite(
                tuple(rest),
                accumulated if value in accumulated else (*accumulated, value),
                ctx,
            )
        )

    def _coordinate(self, ctx, first_iterable=None):
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
                            "py.setcomp",
                            [
                                _floor_as_term(elt, owner=str(self.site)),
                                *generator_args,
                            ],
                        )
                    )
                )
            ),
            first_iterable=first_iterable,
        )

    def walk_children(self):
        return (self.elt_body, *clause_children(self.clauses))
