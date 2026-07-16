from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import ObjectValue, StringValue
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class AttributeDeleteSugar(Sugar, role=SugarRole.STATEMENT):
    receiver: SugarBody
    name: str
    site: object = field(compare=False)

    @classmethod
    def owns(cls, site):
        return (
            site.observed == "Delete"
            and len(site.delete_targets()) == 1
            and site.delete_targets()[0].observed == "Attribute"
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
            "class Box:\n"
            "    def __delattr__(self, name):\n"
            "        return 1\n\n"
            "def A():\n"
            "    box = Box()\n"
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
        return self.receiver.reduce(ctx).and_then(
            lambda receiver: self._delete(receiver, ctx)
        )

    def _delete(self, receiver, ctx):
        if isinstance(receiver, ObjectValue):
            descriptor = receiver.class_field_value(self.name)
            if isinstance(descriptor, ObjectValue) and descriptor.has_method(
                "__delete__"
            ):
                return descriptor.call_method_value(
                    "__delete__",
                    (receiver,),
                    owner=type(self).__name__,
                    blame=str(self.site),
                    ctx=ctx,
                )
            if receiver.has_method("__delattr__"):
                return receiver.call_method_value(
                    "__delattr__",
                    (StringValue(self.name),),
                    owner=type(self).__name__,
                    blame=str(self.site),
                    ctx=ctx,
                )
        return receiver._floor_gap(
            owner=type(self).__name__,
            blame=str(self.site),
            observed=f"{type(receiver).__name__}.{self.name}",
            requested="attribute deletion data-model method",
            fix="construct __delete__ or __delattr__",
        )

    def walk_children(self):
        return (self.receiver,)
