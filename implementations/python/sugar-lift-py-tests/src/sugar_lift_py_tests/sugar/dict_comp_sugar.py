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
class DictCompSugar(Sugar, role=SugarRole.TERM):
    clauses: tuple
    key_body: SugarBody
    value_body: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "DictComp" and supports_clauses(
            site.dictcomp_generators()
        )

    @classmethod
    def new(cls, site, ctx) -> "DictCompSugar":
        return cls(
            clauses=build_clauses(site.dictcomp_generators(), ctx),
            key_body=ctx.build_body(site.dictcomp_key(), SugarRole.TERM),
            value_body=ctx.build_body(site.dictcomp_value(), SugarRole.TERM),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        prefix = "def A(z):\n    y = {x: x for x in z}\n    return 1\n\n"
        return _call_pair(
            name="dict_comp_return",
            owner_sugar="DictCompSugar",
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
        from sugar_lift_py_tests.floor import DictValue, ScopeRebind

        if not remaining:
            return Complete(DictValue(accumulated))
        item, *rest = remaining
        name = self.clauses[0].bindings[0][0]
        item_ctx = ScopeRebind(name, item).extend_scope(ctx)
        return self.key_body.reduce(item_ctx).and_then(
            lambda key: self.value_body.reduce(item_ctx).and_then(
                lambda value: self._collect_finite(
                    tuple(rest), self._dict_set(accumulated, key, value), ctx
                )
            )
        )

    @staticmethod
    def _dict_set(entries, key, value):
        updated = list(entries)
        for index, (existing_key, _existing_value) in enumerate(updated):
            if existing_key == key:
                updated[index] = (key, value)
                return tuple(updated)
        return (*entries, (key, value))

    def _coordinate(self, ctx, first_iterable=None):
        from sugar_lift_py_tests.ir import ctor

        return reduce_clauses(
            self.clauses,
            ctx,
            lambda bound_ctx, generator_args: self.key_body.reduce(
                bound_ctx
            ).and_then(
                lambda key: self.value_body.reduce(bound_ctx).and_then(
                    lambda value: Complete(
                        ComprehensionValue(
                            ctor(
                                "py.dictcomp",
                                [
                                    _floor_as_term(key, owner=str(self.site)),
                                    _floor_as_term(value, owner=str(self.site)),
                                    *generator_args,
                                ],
                            )
                        )
                    )
                )
            ),
            first_iterable=first_iterable,
        )

    def walk_children(self):
        return (
            self.key_body,
            self.value_body,
            *clause_children(self.clauses),
        )
