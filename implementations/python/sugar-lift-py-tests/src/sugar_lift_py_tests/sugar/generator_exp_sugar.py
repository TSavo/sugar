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
        finite_prefix = (
            "class Box:\n"
            "    def __init__(self):\n"
            "        self.x = 7\n"
            "\n"
            "def B():\n"
            "    for value in (getattr(Box(), name) for name in ('x',)):\n"
            "        return value\n"
            "    return 0\n"
            "\n"
        )
        return (
            _call_pair(
                name="generator_exp_return",
                owner_sugar="GeneratorExpSugar",
                truthful=prefix + "def test_a():\n    assert A(5) == 1\n",
                lying=prefix + "def test_a():\n    assert A(5) == 0\n",
            ),
            _call_pair(
                name="generator_exp_finite_getattr_return",
                owner_sugar="GeneratorExpSugar",
                truthful=finite_prefix + "def test_b():\n    assert B() == 7\n",
                lying=finite_prefix + "def test_b():\n    assert B() == 8\n",
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
                    construction="GeneratorExpSugar finite collect",
                    site=self.site,
                    observed=f"generator cardinality={len(iterable.elements)}",
                    limit=STATIC_UNFOLD_LIMIT,
                )
            return self._collect_finite(iterable, iterable.elements, (), ctx)
        return self._coordinate(ctx, iterable)

    def _collect_finite(self, iterable, remaining, accumulated, ctx):
        from sugar_lift_py_tests.floor import (
            ComprehensionValue,
            RaiseValue,
            ScopeRebind,
        )
        from sugar_lift_py_tests.ir import ctor
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
        values = tuple(collected)
        return Complete(
            ComprehensionValue(
                ctor(
                    "py.genexp.finite",
                    [
                        iterable.to_term(owner=str(self.site)),
                        *(
                            _floor_as_term(value, owner=str(self.site))
                            for value in values
                        ),
                    ],
                ),
                values,
            )
        )

    def _coordinate(self, ctx, first_iterable=None) -> Outcome:
        from sugar_lift_py_tests.ir import ctor

        return reduce_clauses(
            self.clauses,
            ctx,
            lambda bound_ctx, generator_args: self.elt_body.reduce(bound_ctx).and_then(
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
            first_iterable=first_iterable,
        )

    def walk_children(self):
        return (self.elt_body, *clause_children(self.clauses))
