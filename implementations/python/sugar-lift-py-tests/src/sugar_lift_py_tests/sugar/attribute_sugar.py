from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class AttributeSugar(Sugar, role=SugarRole.TERM):
    """Attribute access `x.attr` is a unary coordinate into the vendor universe.

    LAW (symbolic_term Attribute case): the spelling is
    `call:<attr>(receiver)` -- same head family as methods -- NOT
    `py.attr(receiver, name)`. Reduce the receiver; the result is a
    CallSiteValue whose term IS that coordinate. The lift does not invent
    the attribute's value; the coordinate is the stated address a dig lands
    on, and it rides inside any sentence built over the result.

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
        # Reduce the receiver; the result is the attribute coordinate.
        from sugar_lift_py_tests.floor import CallSiteValue
        from sugar_lift_py_tests.ir import ctor

        return self.receiver.reduce(ctx).and_then(
            lambda value: Complete(
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
        )

    def walk_children(self):
        return (self.receiver,)
