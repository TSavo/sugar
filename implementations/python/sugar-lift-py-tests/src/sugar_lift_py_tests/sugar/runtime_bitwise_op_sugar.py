from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody

_RUNTIME_BITWISE_OPS = {
    "BitAnd": "bitwise_and",
    "BitXor": "bitwise_xor",
    "LShift": "left_shift",
}


@dataclass(frozen=True)
class RuntimeBitwiseOpSugar(Sugar, role=SugarRole.TERM):
    """Runtime-only bitwise BinOps, explicitly excluding ambiguous BitOr."""

    operator: str
    left: SugarBody
    right: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return (
            site.observed == "BinOp"
            and site.operator_kind() in _RUNTIME_BITWISE_OPS
        )

    @classmethod
    def new(cls, site, ctx) -> "RuntimeBitwiseOpSugar":
        return cls(
            operator=site.operator_kind(),
            left=ctx.build_body(site.binop_left(), SugarRole.TERM),
            right=ctx.build_body(site.binop_right(), SugarRole.TERM),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        prefix = "def A():\n    return 6 & 3\n\n"
        return _call_pair(
            name="runtime_bitwise_and_return",
            owner_sugar="RuntimeBitwiseOpSugar",
            truthful=prefix + "def test_a():\n    assert A() == 2\n",
            lying=prefix + "def test_a():\n    assert A() == 3\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        method = _RUNTIME_BITWISE_OPS[self.operator]
        return self.left.reduce(ctx).and_then(
            lambda left: self.right.reduce(ctx).and_then(
                lambda right: getattr(left, method)(right, self.site)
            )
        )

    def walk_children(self):
        return (self.left, self.right)
