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
        finite = (
            "def B():\n"
            "    values = [value if value else 7 for value in [1, 0]]\n"
            "    return values[1]\n\n"
        )
        return (
            _call_pair(
                name="list_comp_return",
                owner_sugar="ListCompSugar",
                truthful=prefix + "def test_a():\n    assert A(5) == 1\n",
                lying=prefix + "def test_a():\n    assert A(5) == 0\n",
            ),
            _call_pair(
                name="list_comp_finite_conditional",
                owner_sugar="ListCompSugar",
                truthful=finite + "def test_b():\n    assert B() == 7\n",
                lying=finite + "def test_b():\n    assert B() == 0\n",
                family="finite-list-comprehension",
            ),
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
        from sugar_lift_py_tests.sugar.for_sugar import (
            STATIC_UNFOLD_LIMIT,
            finite_unfold_cap_panic,
        )

        if isinstance(iterable, (ListValue, TupleValue)):
            if len(iterable.elements) > STATIC_UNFOLD_LIMIT:
                finite_unfold_cap_panic(
                    construction="ListCompSugar finite collect",
                    site=self.site,
                    observed=f"list-comprehension cardinality={len(iterable.elements)}",
                    limit=STATIC_UNFOLD_LIMIT,
                )
            return self._collect_finite(iterable.elements, (), ctx)
        return self._coordinate(ctx, iterable)

    def _collect_finite(self, remaining, accumulated, ctx):
        from sugar_lift_py_tests.floor import ListValue, RaiseValue, ScopeRebind
        from sugar_lift_py_tests.outcome import Complete, Incomplete

        name = self.clauses[0].bindings[0][0]
        collected = list(accumulated)
        for item in remaining:
            item_ctx = ScopeRebind(name, item).extend_scope(ctx)
            outcome = self.elt_body.reduce(item_ctx)
            if isinstance(outcome, Incomplete):
                return outcome
            if isinstance(outcome.value, RaiseValue):
                return outcome
            collected.append(outcome.value)
        return Complete(ListValue(tuple(collected)))

    def _coordinate(self, ctx, first_iterable=None) -> Outcome:
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
            first_iterable=first_iterable,
        )

    def walk_children(self):
        return (self.elt_body, *clause_children(self.clauses))
