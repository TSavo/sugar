from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class AbsCallSugar(Sugar, role=SugarRole.TERM, comes_before=("CallSugar",)):
    """The vendor numeric call ``abs(value)``.

    Exactly one positional, non-starred argument to the plain builtin name is
    owned. Keywords, starred arguments, methods, and malformed arities remain
    on the existing CallSugar or loud-gap path.
    """

    arg: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return (
            site.observed == "Call"
            and site.call_receiver() is None
            and site.call_target_name() == "abs"
            and site.call_arg_count() == 1
            and not site.call_has_keywords()
            and not any(arg.observed == "Starred" for arg in site.call_args())
        )

    @classmethod
    def new(cls, site, ctx) -> "AbsCallSugar":
        return cls(
            arg=ctx.build_body(site.call_args()[0], SugarRole.TERM),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        prefix = "def A(z):\n    return abs(z)\n\n"
        return _call_pair(
            name="abs_return",
            owner_sugar="AbsCallSugar",
            truthful=prefix + "def test_a():\n    assert A(-5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(-5) == -5\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return self.arg.reduce(ctx).and_then(lambda value: value.absolute(self.site))

    def walk_children(self):
        return (self.arg,)
