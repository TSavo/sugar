from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field, replace
from typing import Any

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import (
    BoundVar,
    FloorValue,
    TermValue,
)
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class TupleUnpackBindings(FloorValue):
    bindings: tuple[FloorValue, ...]

    def contribution(self):
        return ()

    def extend_scope(self, ctx):
        scoped = ctx
        for binding in self.bindings:
            scoped = binding.extend_scope(scoped)
        return replace(ctx, temporal=scoped.temporal)


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
class TupleNameStore:
    name: str
    projection: SugarBody

    def desugar(self, ctx: Any = None) -> Outcome:
        return Complete(BoundVar(self.name, self.projection, scope=ctx))

    def walk_children(self):
        return (self.projection,)


@dataclass(frozen=True)
class TupleUnpackAssignSugar(Sugar, role=SugarRole.STATEMENT):
    """One tuple target whose leaves have static name-rooted addresses.

    Each leaf receives an indexed projection of the same factory-built rhs source.
    Name leaves bind temporally; dotted attribute and subscript leaves reuse the
    ordinary store owners. Starred leaves stay unowned.
    """

    stores: tuple[SugarBody, ...]
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        """Own any single-tuple Assign whose leaves are name-rooted stores.

        ``new`` already builds Name / Attribute / nested-Attribute / Subscript
        leaves via the ordinary store owners. ``owns`` must match that partition:
        previously only flat Name leaves were claimed, so every
        ``a[i], b[j] = …`` / ``obj.x, obj.y = …`` / nested ``(a, b), c = …``
        site fell through to python.factory (dominant post-#5250 mass). Starred
        leaves stay with SequenceUnpackAssignSugar; unrooted call receivers stay
        unowned and panic.
        """
        if site.observed != "Assign":
            return False
        targets = site.assign_targets()
        if len(targets) != 1 or targets[0].observed != "Tuple":
            return False
        elements = targets[0].tuple_elts()
        if not elements:
            return False
        # Structural claim: every leaf must be a static name-rooted store.
        # _target_leaves returns None for Starred / call-rooted / unknown.
        leaves = _target_leaves(targets[0])
        if not leaves:
            return False
        value = site.assign_value()
        if value.observed in {"Tuple", "List"}:
            values = (
                value.tuple_elts() if value.observed == "Tuple" else value.list_elts()
            )
            # Top-level arity only (nested structure is projected by path).
            return len(values) == len(elements)
        return True

    @classmethod
    def new(cls, site, ctx) -> "TupleUnpackAssignSugar":
        target = site.assign_targets()[0]
        leaves = _target_leaves(target)
        receiver = ctx.build_body(site.assign_value(), SugarRole.TERM)
        stores = []
        from sugar_lift_py_tests.sugar.attribute_assign_sugar import (
            AttributeAssignSugar,
        )
        from sugar_lift_py_tests.sugar.name_sugar import NameSugar
        from sugar_lift_py_tests.sugar.nested_attribute_assign_sugar import (
            NestedAttributeAssignSugar,
        )
        from sugar_lift_py_tests.sugar.subscript_assign_sugar import (
            SubscriptAssignSugar,
        )

        for kind, first, second, path in leaves:
            projection = _projection(receiver, path, site)
            if kind == "name":
                stores.append(
                    SugarBody(TupleNameStore(first, projection), SugarRole.STATEMENT)
                )
            elif kind == "subscript":
                stores.append(
                    SugarBody(
                        SubscriptAssignSugar.from_target(
                            first,
                            projection,
                            site,
                            ctx,
                        ),
                        SugarRole.STATEMENT,
                    )
                )
            elif len(first) >= 3:
                stores.append(
                    SugarBody(
                        NestedAttributeAssignSugar(
                            path=first,
                            value=projection,
                            site=site,
                        ),
                        SugarRole.STATEMENT,
                    )
                )
            else:
                receiver_name, field_name = first
                receiver_body = SugarBody(
                    NameSugar(receiver_name, site), SugarRole.TERM
                )
                stores.append(
                    SugarBody(
                        AttributeAssignSugar(
                            receiver_name=receiver_name,
                            field_name=field_name,
                            receiver=receiver_body,
                            value=projection,
                            site=site,
                        ),
                        SugarRole.STATEMENT,
                    )
                )
        return cls(
            stores=tuple(stores),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        prefix = "def A():\n    a, b = (2, 3)\n    return a + b\n\n"
        module_prefix = (
            "pair = (2, 3)\n"
            "a, b = pair\n"
            "def B(value=a):\n"
            "    return value\n"
            "\n"
        )
        return (
            _call_pair(
                name="tuple_unpack_assign_return",
                owner_sugar="TupleUnpackAssignSugar",
                truthful=prefix + "def test_a():\n    assert A() == 5\n",
                lying=prefix + "def test_a():\n    assert A() == 6\n",
            ),
            _call_pair(
                name="module_tuple_unpack_execution_order",
                owner_sugar="TupleUnpackAssignSugar",
                truthful=module_prefix + "def test_b():\n    assert B(a) == 2\n",
                lying=module_prefix + "def test_b():\n    assert B(a) == 3\n",
                family="module-execution-order",
            ),
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return self._reduce_stores(self.stores, (), ctx)

    def _reduce_stores(self, remaining, accumulated, ctx):
        if not remaining:
            return Complete(TupleUnpackBindings(accumulated))
        head, *rest = remaining
        return head.reduce(ctx).and_then(
            lambda value: self._reduce_stores(
                tuple(rest), (*accumulated, value), value.extend_scope(ctx)
            )
        )

    def walk_children(self):
        return self.stores


def _target_leaves(target, prefix=()):
    if target.observed == "Name":
        return (("name", target.name_id(), None, prefix),)
    if target.observed == "Attribute":
        path = _attribute_path(target)
        if path is None:
            return None
        return (("attribute", path, None, prefix),)
    if target.observed == "Subscript":
        return (("subscript", target, None, prefix),)
    if target.observed not in {"Tuple", "List"}:
        return None
    elements = target.tuple_elts() if target.observed == "Tuple" else target.list_elts()
    if not elements:
        return None
    bindings = []
    for index, element in enumerate(elements):
        nested = _target_leaves(element, (*prefix, index))
        if nested is None:
            return None
        bindings.extend(nested)
    return tuple(bindings)


def _attribute_path(target):
    parts = []
    current = target
    while current.observed == "Attribute":
        parts.append(current.attr_name())
        current = current.attr_receiver()
    if current.observed != "Name":
        return None
    return (current.name_id(), *reversed(parts))


def _projection(receiver, path, site):
    projected = receiver
    for index in path:
        projected = SugarBody(
            TupleElementProjection(receiver=projected, index=index, site=site),
            SugarRole.TERM,
        )
    return projected


from sugar_lift_py_tests.sugar.sequence_unpack_assign_sugar import (
    SequenceUnpackAssignSugar,
    SequenceUnpackBindings,
)
