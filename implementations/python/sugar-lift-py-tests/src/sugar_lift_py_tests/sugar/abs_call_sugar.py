from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import Any

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class AbsCallSugar(Sugar, role=SugarRole.TERM, comes_before=("CallSugar",)):
    """The vendor numeric call ``abs(value)``.

    Exactly one positional, non-starred numeric-shaped argument to the plain
    builtin name is owned. Obvious nonnumeric literals, keywords, starred
    arguments, methods, and malformed arities remain on the loud None arm.
    """

    arg: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        if not (
            site.observed == "Call"
            and site.call_receiver() is None
            and site.call_target_name() == "abs"
            and site.call_arg_count() == 1
            and not site.call_has_keywords()
            and not any(arg.observed == "Starred" for arg in site.call_args())
        ):
            return False
        return _numeric_operand_shape(site.call_args()[0])

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

    def desugar(self, ctx: Any = None) -> Outcome:
        from sugar_lift_py_tests.floor import ObjectValue

        return self.arg.reduce(ctx).and_then(
            lambda value: value.call_method_value(
                "__abs__", (), owner=type(self).__name__, blame=str(self.site), ctx=ctx
            )
            if isinstance(value, ObjectValue)
            else value.absolute(self.site)
        )

    def walk_children(self):
        return (self.arg,)


def _numeric_operand_shape(arg) -> bool:
    if arg.observed == "PrimitiveLiteral":
        return type(arg.literal_value()) in {int, float}
    return arg.observed in {
        "Name",
        "BinOp",
        "UnaryOp",
        "Call",
        "Attribute",
        "Subscript",
    }
