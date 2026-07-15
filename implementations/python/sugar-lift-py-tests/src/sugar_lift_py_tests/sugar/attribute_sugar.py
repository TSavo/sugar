from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


def _receiver_name_from_body(receiver: SugarBody) -> str | None:
    """Dotted source spelling of a Name/Attribute receiver SugarBody."""
    sugar = getattr(receiver, "sugar", None)
    name = getattr(sugar, "name", None)
    if isinstance(name, str) and name:
        return name
    attr_name = getattr(sugar, "attr_name", None)
    nested_receiver = getattr(sugar, "receiver", None)
    if isinstance(attr_name, str) and isinstance(nested_receiver, SugarBody):
        prefix = _receiver_name_from_body(nested_receiver)
        if prefix is not None:
            return f"{prefix}.{attr_name}"
    return None


def _temporal_lookup(ctx: object, name: str):
    """Soft temporal bind lookup — None when unbound (never invent / never panic)."""
    if ctx is None:
        return None
    temporal = getattr(ctx, "temporal", None)
    if temporal is None:
        return None
    bindings = getattr(temporal, "bindings", None) or ()
    for binding in reversed(bindings):
        if getattr(binding, "name", None) == name:
            return getattr(binding, "value", None)
    return None


@dataclass(frozen=True)
class AttributeSugar(Sugar, role=SugarRole.TERM):
    """Attribute access `x.attr` is a unary coordinate into the vendor universe.

    LAW (symbolic_term Attribute case): the spelling is
    `call:<attr>(receiver)` -- same head family as methods -- NOT
    `py.attr(receiver, name)`. Reduce the receiver; the result is a
    CallSiteValue whose term IS that coordinate. The lift does not invent
    the attribute's value; the coordinate is the stated address a dig lands
    on, and it rides inside any sentence built over the result.

    Attribute-on-self dig path: when dig/body has already assigned
    ``receiver.attr`` (AttributeAssignSugar → ScopeRebind key ``name.attr``),
    prefer that temporal value over the opaque coordinate. Same for
    ObjectValue field tables when the receiver floor carries fields. Missing
    binds stay coordinate-only — never invent.

    owns: any Attribute site at TERM role. CallSugar / OsSugar own the Call
    node of `x.m()` / `os.exit(...)`, not the func Attribute child -- those
    sugars never build the func as a TERM, so AttributeSugar only fires when
    the Attribute itself is demanded as a term (bare `x.attr`, or as an
    argument/expression). The shapes are disjoint.
    """

    attr_name: str
    receiver: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "Attribute"

    @classmethod
    def new(cls, site, ctx) -> "AttributeSugar":
        # The receiver is factory-built (audited), never reduced here.
        return cls(
            attr_name=site.attr_name(),
            receiver=ctx.build_body(site.attr_receiver(), SugarRole.TERM),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        # Attribute coordinate is built in the body; the pair discriminates on
        # the return face the same way CallSugar's witnesses do.
        prefix = "def A(x):\n" "    y = x.shape\n" "    return 1\n" "\n"
        return _call_pair(
            name="attribute_return",
            owner_sugar="AttributeSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 1\n",
            lying=prefix + "def test_a():\n    assert A(5) == 0\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.floor.bound_var import BoundVar

        # Attribute-on-self / ScopeRebind path: Name.attr may already be bound
        # as temporal key "name.attr" (AttributeAssignSugar). Prefer dig-known
        # field over opaque call:attr(name). Unbound → coordinate below.
        recv_name = _receiver_name_from_body(self.receiver)
        if recv_name is not None:
            key = f"{recv_name}.{self.attr_name}"
            bound = _temporal_lookup(ctx, key)
            if bound is not None:
                if isinstance(bound, BoundVar):
                    return bound.answer(ctx)
                return Complete(bound)

        return self.receiver.reduce(ctx).and_then(
            lambda value: self._project_attribute(value, ctx)
        )

    def _project_attribute(self, value, ctx: object) -> Outcome:
        from sugar_lift_py_tests.floor import CallSiteValue, ObjectValue, StringValue
        from sugar_lift_py_tests.ir import ctor

        if isinstance(value, ObjectValue):
            return project_object_attribute(value, self.attr_name, self.site, ctx)

        # ObjectValue / field table: resolve known fields, else coordinate.
        fields = getattr(value, "fields", None)
        if fields is not None:
            for field in fields:
                if getattr(field, "name", None) == self.attr_name:
                    field_val = getattr(field, "value", None)
                    if field_val is not None:
                        return Complete(field_val)

        if isinstance(value, ObjectValue):
            if value.has_method(self.attr_name):
                return value._floor_gap(
                    owner=type(self).__name__,
                    blame=self.site,
                    observed=f"{value.class_name}.{self.attr_name}",
                    requested="bound method attribute floor",
                    fix="construct a bound method value before bare attribute access",
                )
            if value.has_method("__getattr__"):
                return value.call_method_value(
                    "__getattr__",
                    (StringValue(self.attr_name),),
                    owner=type(self).__name__,
                    blame=self.site,
                    ctx=ctx,
                )
            return value._floor_gap(
                owner=type(self).__name__,
                blame=self.site,
                observed=f"{value.class_name}.{self.attr_name}",
                requested="constructor-bound field",
                fix=f"construct field `{value.class_name}.{self.attr_name}` or __getattr__",
            )

        return Complete(
            CallSiteValue(
                target_name=self.attr_name,
                arg_values=(value,),
                parameters=(),
                term=ctor(
                    f"call:{self.attr_name}",
                    [value.to_term(owner=str(self.site))],
                    symbol_kind="method-coordinate",
                ),
                body=None,
                site=self.site,
            )
        )

    def walk_children(self):
        return (self.receiver,)


def project_object_attribute(value, attr_name: str, site, ctx) -> Outcome:
    from sugar_lift_py_tests.floor import ObjectValue, StringValue
    from sugar_lift_py_tests.outcome import Complete

    name = StringValue(attr_name)
    if value.has_method("__getattribute__"):
        return value.call_method_value(
            "__getattribute__",
            (name,),
            owner="AttributeSugar",
            blame=site,
            ctx=ctx,
        )
    descriptor = value.class_field_value(attr_name)
    if isinstance(descriptor, ObjectValue) and descriptor.has_method("__get__"):
        return descriptor.call_method_value(
            "__get__",
            (value, StringValue(value.class_name)),
            owner="AttributeSugar",
            blame=site,
            ctx=ctx,
        )
    for object_field in value.fields:
        if object_field.name == attr_name:
            return Complete(object_field.value)
    if value.has_method(attr_name):
        return value._floor_gap(
            owner="AttributeSugar",
            blame=site,
            observed=f"{value.class_name}.{attr_name}",
            requested="bound method attribute floor",
            fix="construct a bound method value before bare attribute access",
        )
    if value.has_method("__getattr__"):
        return value.call_method_value(
            "__getattr__", (name,), owner="AttributeSugar", blame=site, ctx=ctx
        )
    return value._floor_gap(
        owner="AttributeSugar",
        blame=site,
        observed=f"{value.class_name}.{attr_name}",
        requested="constructor-bound field",
        fix=f"construct field `{value.class_name}.{attr_name}` or __getattr__",
    )
