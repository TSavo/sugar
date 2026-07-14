from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field, replace

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import BoundVar, FloorValue
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class ChainedBindings(FloorValue):
    bindings: tuple[FloorValue, ...]

    def contribution(self):
        return ()

    def extend_scope(self, ctx):
        scoped = ctx
        for binding in self.bindings:
            scoped = binding.extend_scope(scoped)
        return replace(ctx, temporal=scoped.temporal)


@dataclass(frozen=True)
class ChainedNameStore:
    name: str
    value: SugarBody

    def desugar(self, ctx=None) -> Outcome:
        return Complete(BoundVar(self.name, self.value, scope=ctx))

    def walk_children(self):
        return (self.value,)


@dataclass(frozen=True)
class ChainedAssignSugar(Sugar, role=SugarRole.STATEMENT):
    """Chained assignment as an ordered sequence of ordinary stores.

    Every target receives the same factory-built rhs source. Name, name-rooted
    attribute, and subscript targets reuse their existing store constructions.
    Tuple, list, starred, and dynamically rooted attribute targets stay unowned.
    """

    stores: tuple[SugarBody, ...]
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "Assign":
            return False
        targets = site.assign_targets()
        return len(targets) > 1 and all(
            _target_is_supported(target) for target in targets
        )

    @classmethod
    def new(cls, site, ctx) -> "ChainedAssignSugar":
        targets = site.assign_targets()
        value = ctx.build_body(site.assign_value(), SugarRole.TERM)
        return cls(
            stores=tuple(_target_store(target, value, site, ctx) for target in targets),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        prefix = "def A():\n    a = b = 5\n    return a + b\n\n"
        return _call_pair(
            name="chained_assign_return",
            owner_sugar="ChainedAssignSugar",
            truthful=prefix + "def test_a():\n    assert A() == 10\n",
            lying=prefix + "def test_a():\n    assert A() == 11\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return self._reduce_stores(self.stores, (), ctx)

    def _reduce_stores(self, remaining, accumulated, ctx):
        if not remaining:
            return Complete(ChainedBindings(accumulated))
        head, *rest = remaining
        return head.reduce(ctx).and_then(
            lambda binding: self._reduce_stores(
                tuple(rest),
                (*accumulated, binding),
                binding.extend_scope(ctx),
            )
        )

    def walk_children(self):
        return self.stores


def _target_is_supported(target) -> bool:
    if target.observed in {"Name", "Subscript"}:
        return True
    return target.observed == "Attribute" and _attribute_path(target) is not None


def _attribute_path(target) -> tuple[str, ...] | None:
    parts = []
    current = target
    while current.observed == "Attribute":
        parts.append(current.attr_name())
        current = current.attr_receiver()
    if current.observed != "Name":
        return None
    return (current.name_id(), *reversed(parts))


def _target_store(target, value, site, ctx) -> SugarBody:
    from sugar_lift_py_tests.sugar.attribute_assign_sugar import AttributeAssignSugar
    from sugar_lift_py_tests.sugar.name_sugar import NameSugar
    from sugar_lift_py_tests.sugar.nested_attribute_assign_sugar import (
        NestedAttributeAssignSugar,
    )
    from sugar_lift_py_tests.sugar.subscript_assign_sugar import SubscriptAssignSugar

    if target.observed == "Name":
        store = ChainedNameStore(target.name_id(), value)
    elif target.observed == "Subscript":
        receiver = target.subscript_receiver()
        store = SubscriptAssignSugar(
            receiver=ctx.build_body(receiver, SugarRole.TERM),
            receiver_name=(receiver.name_id() if receiver.observed == "Name" else None),
            index=ctx.build_body(target.subscript_index(), SugarRole.TERM),
            value=value,
            site=site,
        )
    else:
        path = _attribute_path(target)
        if path is None:
            raise AssertionError(
                "ChainedAssignSugar built an unsupported attribute target"
            )
        if len(path) >= 3:
            store = NestedAttributeAssignSugar(path=path, value=value, site=site)
        else:
            receiver_name, field_name = path
            store = AttributeAssignSugar(
                receiver_name=receiver_name,
                field_name=field_name,
                receiver=SugarBody(NameSugar(receiver_name, site), SugarRole.TERM),
                value=value,
                site=site,
            )
    return SugarBody(store, SugarRole.STATEMENT)
