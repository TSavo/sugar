from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class TupleForSugar(Sugar, role=SugarRole.STATEMENT):
    """A flat all-name loop target over one iterable element address.

    The loop element remains the existing ``py.iter_elem(iterable)``
    coordinate. Each target name binds to its indexed projection before the
    body reduces. Nested or starred targets and loop ``else`` remain separate
    loud partitions.
    """

    names: tuple[str, ...]
    iterable: SugarBody
    body: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "For" or site.for_orelse_count() != 0:
            return False
        names = site.for_flat_tuple_target_names()
        return names is not None and len(names) >= 2

    @classmethod
    def new(cls, site, ctx) -> "TupleForSugar":
        names = site.for_flat_tuple_target_names()
        return cls(
            names=tuple(names),
            iterable=ctx.build_body(site.for_iter(), SugarRole.TERM),
            body=ctx.build_body(site.for_body_block(), SugarRole.STATEMENT),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        prefix = (
            "def A(z):\n"
            "    for left, right in [(z, 2)]:\n"
            "        return 1\n"
            "    return 0\n\n"
        )
        return _call_pair(
            name="tuple_for_return",
            owner_sugar="TupleForSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 1\n",
            lying=prefix + "def test_a():\n    assert A(5) == 0\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return self.iterable.reduce(ctx).and_then(
            lambda iterable: self._bind_targets_and_body(iterable, ctx)
        )

    def _bind_targets_and_body(self, iterable, ctx: object) -> Outcome:
        from sugar_lift_py_tests.floor import CallSiteValue
        from sugar_lift_py_tests.ir import ctor, num

        element = CallSiteValue(
            target_name="iter_elem",
            arg_values=(iterable,),
            parameters=(),
            term=ctor(
                "py.iter_elem",
                [iterable.to_term(owner=str(self.site))],
            ),
            body=None,
            site=self.site,
        )
        temporal = ctx.temporal
        for index, name in enumerate(self.names):
            temporal = temporal.bind_value(
                name,
                CallSiteValue(
                    target_name="py.subscript",
                    arg_values=(element,),
                    parameters=(),
                    term=ctor("py.subscript", [element.term, num(index)]),
                    body=None,
                    site=self.site,
                ),
            )
        return self.body.reduce(ctx.with_temporal(temporal))

    def walk_children(self):
        return (self.iterable, self.body)
