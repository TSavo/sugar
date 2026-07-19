from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class StarredTupleForSugar(Sugar, role=SugarRole.STATEMENT):
    """``for a, b, *_ in rows:`` — bind non-star names; discard unused rest.

    Exactly one starred leaf, and that name must not be loaded in the For
    site (same discarded-star partition as SetComp). Used-star and
    multi-star targets stay outside owns and remain loud FactoryPanic.
    """

    targets: tuple[tuple[tuple[int, ...], str], ...]
    iterable: SugarBody
    body: SugarBody
    site: object = dataclass_field(compare=False)

    @staticmethod
    def recognize_target_paths(site):
        from sugar_lift_py_tests.recognition.binding_shapes import (
            BindingShapeRecognition,
        )

        return BindingShapeRecognition.for_discarded_star_tuple_target_paths(site)

    @classmethod
    def owns(cls, site) -> bool:
        return (
            site.observed == "For"
            and site.for_orelse_count() == 0
            and site.for_discarded_star_tuple_target_paths() is not None
        )

    @classmethod
    def new(cls, site, ctx) -> "StarredTupleForSugar":
        return cls(
            targets=site.for_discarded_star_tuple_target_paths(),
            iterable=ctx.build_body(site.for_iter(), SugarRole.TERM),
            body=ctx.build_body(site.for_body_block(), SugarRole.STATEMENT),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        # sklearn compose/_column_transformer shape: trailing discarded star.
        prefix = (
            "def A(rows):\n"
            "    for name, trans, *_ in rows:\n"
            "        return name\n"
            "    return 0\n\n"
        )
        return _call_pair(
            name="starred_tuple_for_discard_return",
            owner_sugar=cls.__name__,
            truthful=prefix + "def test_a():\n    assert A([]) == 0\n",
            lying=prefix + "def test_a():\n    assert A([]) == 1\n",
        )

    def desugar(self, ctx=None) -> Outcome:
        return self.iterable.reduce(ctx).and_then(
            lambda iterable: self._bind_and_reduce(iterable, ctx)
        )

    def _bind_and_reduce(self, iterable, ctx) -> Outcome:
        from sugar_lift_py_tests.floor import (
            BlockValue,
            CallSiteValue,
            ListValue,
            TupleValue,
        )
        from sugar_lift_py_tests.ir import ctor, num
        from sugar_lift_py_tests.outcome import Complete

        # Empty concrete sequences do zero iterations — same empty-list door as
        # NestedTupleForSugar so the empty-rows witness fall-through digs.
        if type(iterable) is ListValue and not iterable.elements:
            return Complete(BlockValue(()))
        if type(iterable) is TupleValue and not iterable.elements:
            return Complete(BlockValue(()))

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
