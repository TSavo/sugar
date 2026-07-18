from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import ObjectValue, StringValue
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody
from sugar_lift_py_tests.recognition.delete_targets import (
    DeleteTargetKind,
    DeleteTargetRecognition,
)


@dataclass(frozen=True)
class AttributeDeleteSugar(Sugar, role=SugarRole.STATEMENT):
    receiver: SugarBody
    name: str
    site: object = field(compare=False)

    @classmethod
    def owns(cls, site):
        targets = DeleteTargetRecognition.statement_targets(site)
        return (
            targets is not None
            and len(targets) == 1
            and targets[0].kind is DeleteTargetKind.ATTRIBUTE
        )

    @classmethod
    def new(cls, site, ctx):
        target = site.delete_targets()[0]
        return cls(
            ctx.build_body(target.attr_receiver(), SugarRole.TERM),
            target.attr_name(),
            site,
        )

    @classmethod
    def witnesses(cls):
        prefix = (
            "def A():\n"
            "    class Box:\n"
            "        pass\n"
            "    box = Box()\n"
            "    box.value = 1\n"
            "    del box.value\n"
            "    return 1\n\n"
        )
        return _call_pair(
            name="attribute_delete_dunder",
            owner_sugar=cls.__name__,
            truthful=prefix + "def test_a():\n    assert A() == 1\n",
            lying=prefix + "def test_a():\n    assert A() == 2\n",
        )

    def desugar(self, ctx=None) -> Outcome:
        return delete_attribute_body(
            receiver=self.receiver,
            name=self.name,
            site=self.site,
            ctx=ctx,
        )

    def walk_children(self):
        return (self.receiver,)


def delete_attribute_body(*, receiver, name, site, ctx) -> Outcome:
    """Dispatch attribute deletion for a factory-built receiver body."""
    from sugar_lift_py_tests.sugar.attribute_sugar import (
        _receiver_name_from_body,
        _temporal_lookup,
    )
    from sugar_lift_py_tests.sugar.delete_sugar import DeletedBindings

    receiver_name = _receiver_name_from_body(receiver)
    if receiver_name is not None:
        key = f"{receiver_name}.{name}"
        if _temporal_lookup(ctx, key) is not None:
            return Complete(DeletedBindings((key,)))

    return receiver.reduce(ctx).and_then(
        lambda value: delete_attribute_value(
            receiver=value,
            name=name,
            site=site,
            ctx=ctx,
        )
    )


def delete_attribute_value(*, receiver, name, site, ctx) -> Outcome:
    """Use the existing object data-model floor for attribute deletion."""
    if isinstance(receiver, ObjectValue):
        descriptor = receiver.class_field_value(name)
        if isinstance(descriptor, ObjectValue) and descriptor.has_method("__delete__"):
            return descriptor.call_method_value(
                "__delete__",
                (receiver,),
                owner="AttributeDeleteSugar",
                blame=site,
                ctx=ctx,
            )
        if receiver.has_method("__delattr__"):
            return receiver.call_method_value(
                "__delattr__",
                (StringValue(name),),
                owner="AttributeDeleteSugar",
                blame=site,
                ctx=ctx,
            )
    return receiver._floor_gap(
        owner="AttributeDeleteSugar",
        blame=site,
        observed=f"{type(receiver).__name__}.{name}",
        requested="attribute deletion data-model method",
        fix="construct __delete__ or __delattr__",
    )
