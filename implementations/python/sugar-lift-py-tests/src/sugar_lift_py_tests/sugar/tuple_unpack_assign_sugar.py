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
    """One tuple target whose leaves are all names.

    Each name aliases an indexed projection of the same factory-built rhs source.
    Starred, attribute, subscript, chained, and statically mismatched targets
    stay unowned so factory dispatch reaches its loud None arm.
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
        bindings = _target_paths(targets[0])
        if not bindings:
            return False
        return True

    @classmethod
    def new(cls, site, ctx) -> "TupleUnpackAssignSugar":
        target = site.assign_targets()[0]
        bindings = _target_paths(target)
        names = tuple(name for name, _path in bindings)
        receiver = ctx.build_body(site.assign_value(), SugarRole.TERM)
        return cls(
            names=names,
            projections=tuple(
                _projection(receiver, path, site)
                for _name, path in bindings
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


def _target_paths(target, prefix=()):
    if target.observed == "Name":
        return ((target.name_id(), prefix),)
    if target.observed not in {"Tuple", "List"}:
        return None
    elements = target.tuple_elts() if target.observed == "Tuple" else target.list_elts()
    if not elements:
        return None
    bindings = []
    for index, element in enumerate(elements):
        nested = _target_paths(element, (*prefix, index))
        if nested is None:
            return None
        bindings.extend(nested)
    return tuple(bindings)


def _projection(receiver, path, site):
    projected = receiver
    for index in path:
        projected = SugarBody(
            TupleElementProjection(receiver=projected, index=index, site=site),
            SugarRole.TERM,
        )
    return projected
