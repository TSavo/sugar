from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class NestedTupleForSugar(Sugar, role=SugarRole.STATEMENT):
    """Bind nested tuple names to projections of one iteration address."""

    targets: tuple[tuple[tuple[int, ...], str], ...]
    iterable: SugarBody
    body: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return (
            site.observed == "For"
            and site.for_orelse_count() == 0
            and site.for_nested_tuple_target_paths() is not None
        )

    @classmethod
    def new(cls, site, ctx) -> "NestedTupleForSugar":
        return cls(
            targets=site.for_nested_tuple_target_paths(),
            iterable=ctx.build_body(site.for_iter(), SugarRole.TERM),
            body=ctx.build_body(site.for_body_block(), SugarRole.STATEMENT),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        prefix = (
            "def A(rows):\n"
            "    for i, (label, size) in rows:\n"
            "        return size\n"
            "    return 0\n\n"
        )
        return _call_pair(
            name="nested_tuple_for_return",
            owner_sugar=cls.__name__,
            truthful=prefix + "def test_a():\n    assert A([]) == 0\n",
            lying=prefix + "def test_a():\n    assert A([]) == 1\n",
        )

    def desugar(self, ctx=None) -> Outcome:
        return self.iterable.reduce(ctx).and_then(
            lambda iterable: self._bind_and_reduce(iterable, ctx)
        )

    def _bind_and_reduce(self, iterable, ctx) -> Outcome:
        from sugar_lift_py_tests.floor import CallSiteValue
        from sugar_lift_py_tests.ir import ctor, num

        element = CallSiteValue(
            target_name="iter_elem",
            arg_values=(iterable,),
            parameters=(),
            term=ctor("py.iter_elem", [iterable.to_term(owner=str(self.site))]),
            body=None,
            site=self.site,
        )
        temporal = ctx.temporal
        for path, name in self.targets:
            term = element.term
            for index in path:
                term = ctor("py.subscript", [term, num(index)])
            temporal = temporal.bind_value(
                name,
                CallSiteValue(
                    target_name="py.subscript",
                    arg_values=(element,),
                    parameters=(),
                    term=term,
                    body=None,
                    site=self.site,
                ),
            )
        return self.body.reduce(ctx.with_temporal(temporal))

    def walk_children(self):
        return (self.iterable, self.body)
