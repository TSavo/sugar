from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class StarredSugar(Sugar, role=SugarRole.TERM):
    """``*args`` expansion in a call argument list.

    Coordinate ``py.star(<value>)`` — recognition + term projection. Does not
    invent unpacking; dig/callsites treat it as an address component.
    """

    value: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "Starred"

    @classmethod
    def new(cls, site, ctx) -> "StarredSugar":
        return cls(
            value=ctx.build_body(site.starred_value(), SugarRole.TERM),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        # Star rides inside a call coordinate; pair discriminates on return face.
        prefix = (
            "def pack(*xs):\n"
            "    return 1\n"
            "\n"
            "def A(z):\n"
            "    ys = (z,)\n"
            "    return pack(*ys)\n"
            "\n"
        )
        return _call_pair(
            name="starred_call_return",
            owner_sugar="StarredSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 1\n",
            lying=prefix + "def test_a():\n    assert A(5) == 0\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.floor import CallSiteValue
        from sugar_lift_py_tests.ir import ctor

        return self.value.reduce(ctx).and_then(
            lambda v: Complete(
                CallSiteValue(
                    target_name="*",
                    arg_values=(v,),
                    parameters=(),
                    term=ctor(
                        "py.star",
                        [v.to_term(owner=str(self.site))],
                    ),
                    body=None,
                    site=self.site,
                )
            )
        )

    def walk_children(self):
        return (self.value,)
