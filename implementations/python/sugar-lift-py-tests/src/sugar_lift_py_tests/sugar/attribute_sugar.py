from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


def _receiver_name_from_body(receiver: SugarBody) -> str | None:
    """Bare Name spelling of an attribute receiver, if the sugar is NameSugar."""
    sugar = getattr(receiver, "sugar", None)
    name = getattr(sugar, "name", None)
    return name if isinstance(name, str) and name else None


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
        prefix = (
            "def A(x):\n"
            "    y = x.shape\n"
            "    return 1\n"
            "\n"
        )
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
        from sugar_lift_py_tests.floor import CallSiteValue
        from sugar_lift_py_tests.ir import ctor

        # ObjectValue / field table: resolve known fields, else coordinate.
        fields = getattr(value, "fields", None)
        if fields is not None:
            for field in fields:
                if getattr(field, "name", None) == self.attr_name:
                    field_val = getattr(field, "value", None)
                    if field_val is not None:
                        return Complete(field_val)

        return Complete(
            CallSiteValue(
                target_name=self.attr_name,
                arg_values=(value,),
                parameters=(),
                term=ctor(
                    f"call:{self.attr_name}",
                    [value.to_term(owner=str(self.site))],
                ),
                body=None,
                site=self.site,
            )
        )

    def walk_children(self):
        return (self.receiver,)
