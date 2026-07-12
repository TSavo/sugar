from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field, replace
from typing import Any

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import BoundVar, FloorValue, TermValue
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class TupleUnpackBindings(FloorValue):
    bindings: tuple[BoundVar, ...]

    def contribution(self):
        return ()

    def extend_scope(self, ctx):
        temporal = ctx.temporal
        for binding in self.bindings:
            temporal = temporal.bind_value(binding.name, binding)
        return replace(ctx, temporal=temporal)


@dataclass(frozen=True)
class TupleElementProjection:
    receiver: SugarBody
    index: int
    site: object = dataclass_field(compare=False)

    def desugar(self, ctx: Any = None) -> Outcome:
        return self.receiver.reduce(ctx).and_then(
            lambda receiver: receiver.subscript(TermValue(self.index), self.site)
        )

    def walk_children(self):
        return (self.receiver,)


@dataclass(frozen=True)
class TupleUnpackAssignSugar(Sugar, role=SugarRole.STATEMENT):
    """One flat tuple target whose elements are all names.

    Each name aliases an indexed projection of the same factory-built rhs source.
    Starred, nested, attribute, subscript, chained, and statically mismatched
    targets stay unowned so factory dispatch reaches its loud None arm.
    """

    names: tuple[str, ...]
    projections: tuple[SugarBody, ...]
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "Assign":
            return False
        targets = site.assign_targets()
        if len(targets) != 1 or targets[0].observed != "Tuple":
            return False
        elements = targets[0].tuple_elts()
        if not elements or not all(element.observed == "Name" for element in elements):
            return False
        rhs = site.assign_value()
        if rhs.observed in {"Tuple", "List"}:
            rhs_elements = (
                rhs.tuple_elts() if rhs.observed == "Tuple" else rhs.list_elts()
            )
            if len(rhs_elements) != len(elements):
                return False
        return True

    @classmethod
    def new(cls, site, ctx) -> "TupleUnpackAssignSugar":
        target = site.assign_targets()[0]
        names = tuple(element.name_id() for element in target.tuple_elts())
        receiver = ctx.build_body(site.assign_value(), SugarRole.TERM)
        return cls(
            names=names,
            projections=tuple(
                SugarBody(
                    TupleElementProjection(receiver=receiver, index=index, site=site),
                    SugarRole.TERM,
                )
                for index in range(len(names))
            ),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        prefix = "def A():\n    a, b = (2, 3)\n    return a + b\n\n"
        return _call_pair(
            name="tuple_unpack_assign_return",
            owner_sugar="TupleUnpackAssignSugar",
            truthful=prefix + "def test_a():\n    assert A() == 5\n",
            lying=prefix + "def test_a():\n    assert A() == 6\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return Complete(
            TupleUnpackBindings(
                tuple(
                    BoundVar(name, projection, scope=ctx)
                    for name, projection in zip(
                        self.names, self.projections, strict=True
                    )
                )
            )
        )

    def walk_children(self):
        return self.projections
