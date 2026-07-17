from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field, replace
from typing import Any

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.effect import (
    SequenceUnpackRuntimeEffect,
    runtime_effect_evidence,
)
from sugar_lift_py_tests.floor import (
    BoundVar,
    FloorValue,
    ListValue,
    ScopeRebind,
    TermValue,
    TupleValue,
)
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome
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
        if site.observed != "Assign":
            return False
        targets = site.assign_targets()
        if len(targets) != 1 or targets[0].observed != "Tuple":
            return False
        leaves = _target_leaves(targets[0])
        if not leaves:
            return False
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
                target_receiver = first.subscript_receiver()
                stores.append(
                    SugarBody(
                        SubscriptAssignSugar(
                            receiver=ctx.build_body(target_receiver, SugarRole.TERM),
                            receiver_name=(
                                target_receiver.name_id()
                                if target_receiver.observed == "Name"
                                else None
                            ),
                            index=ctx.build_body(
                                first.subscript_index(), SugarRole.TERM
                            ),
                            value=projection,
                            site=site,
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
        return _call_pair(
            name="tuple_unpack_assign_return",
            owner_sugar="TupleUnpackAssignSugar",
            truthful=prefix + "def test_a():\n    assert A() == 5\n",
            lying=prefix + "def test_a():\n    assert A() == 6\n",
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


@dataclass(frozen=True)
class SequenceUnpackBindings(FloorValue):
    bindings: tuple[ScopeRebind, ...]

    def contribution(self):
        return ()

    def extend_scope(self, ctx):
        scoped = ctx
        for binding in self.bindings:
            scoped = binding.extend_scope(scoped)
        return replace(ctx, temporal=scoped.temporal)


@dataclass(frozen=True)
class SequenceUnpackAssignSugar(Sugar, role=SugarRole.STATEMENT):
    """List-target or starred unpack with a concrete-cardinality floor."""

    names: tuple[str, ...]
    star_index: int | None
    value: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "Assign":
            return False
        targets = site.assign_targets()
        if len(targets) != 1 or targets[0].observed not in {"Tuple", "List"}:
            return False
        target = targets[0]
        elements = (
            target.tuple_elts() if target.observed == "Tuple" else target.list_elts()
        )
        starred = [
            index for index, item in enumerate(elements) if item.observed == "Starred"
        ]
        if target.observed == "Tuple" and not starred:
            return False
        if len(starred) > 1:
            return False
        return bool(elements) and all(
            item.observed == "Name"
            or (item.observed == "Starred" and item.starred_value().observed == "Name")
            for item in elements
        )

    @classmethod
    def new(cls, site, ctx) -> "SequenceUnpackAssignSugar":
        target = site.assign_targets()[0]
        elements = (
            target.tuple_elts() if target.observed == "Tuple" else target.list_elts()
        )
        star_index = next(
            (
                index
                for index, item in enumerate(elements)
                if item.observed == "Starred"
            ),
            None,
        )
        names = tuple(
            (
                item.starred_value().name_id()
                if item.observed == "Starred"
                else item.name_id()
            )
            for item in elements
        )
        return cls(
            names,
            star_index,
            ctx.build_body(site.assign_value(), SugarRole.TERM),
            site,
        )

    @classmethod
    def witnesses(cls):
        prefix = (
            "def A():\n"
            "    [head, *middle, tail] = (1, 2, 3, 4)\n"
            "    return head + middle[0] + middle[1] + tail\n\n"
        )
        return _call_pair(
            name="sequence_unpack_assign_return",
            owner_sugar=cls.__name__,
            truthful=prefix + "def test_a():\n    assert A() == 10\n",
            lying=prefix + "def test_a():\n    assert A() == 9\n",
        )

    def desugar(self, ctx=None) -> Outcome:
        return self.value.reduce(ctx).and_then(lambda value: self._finish(value))

    def _finish(self, value) -> Outcome:
        if not isinstance(value, (ListValue, TupleValue)):
            return self._runtime_effect(value, "runtime-dependent sequence length")
        elements = value.elements
        if self.star_index is None:
            if len(elements) != len(self.names):
                return self._runtime_effect(value, "unpack arity mismatch")
            values = elements
        else:
            suffix_count = len(self.names) - self.star_index - 1
            minimum = len(self.names) - 1
            if len(elements) < minimum:
                return self._runtime_effect(value, "starred unpack arity mismatch")
            suffix = elements[len(elements) - suffix_count :] if suffix_count else ()
            values = (
                *elements[: self.star_index],
                ListValue(
                    elements[
                        self.star_index : (
                            len(elements) - suffix_count if suffix_count else None
                        )
                    ]
                ),
                *suffix,
            )
        return Complete(
            SequenceUnpackBindings(
                tuple(
                    ScopeRebind(name, bound)
                    for name, bound in zip(self.names, values, strict=True)
                )
            )
        )

    def _runtime_effect(self, value, reason) -> Outcome:
        return Incomplete(
            SequenceUnpackRuntimeEffect(
                f"sequence unpack runtime boundary: {reason}; site={self.site}",
                **runtime_effect_evidence("py.sequence_unpack", value, self.site),
            )
        )

    def walk_children(self):
        return (self.value,)
