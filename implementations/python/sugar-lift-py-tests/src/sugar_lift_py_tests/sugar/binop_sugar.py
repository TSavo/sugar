from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


# Binary operator kind -> the floor method that owns its meaning. The value
# owns what each operation MEANS (ints fold, strings concatenate on `+`, mixed
# types hit the honest gap); this sugar only routes to it. Every entry maps to
# a real FloorValue method, so an operator in this table always reduces or
# reaches the value's own loud gap -- never a silent default.
BINOP_METHODS: dict[str, str] = {
    "Add": "add",
    "Sub": "subtract",
    "Mult": "multiply",
    "MatMult": "matrix_multiply",
    "Div": "divide",
    "Mod": "modulo",
    "Pow": "power",
    "FloorDiv": "floor_divide",
    "LShift": "left_shift",
    "RShift": "right_shift",
    "BitAnd": "bitwise_and",
    "BitOr": "bitwise_or",
    "BitXor": "bitwise_xor",
}


@dataclass(frozen=True)
class BinOpSugar(Sugar):
    """A binary operation `<left> <op> <right>`. It reduces both sides and asks
    the LEFT value to apply the operation against the right -- the value owns
    the answer (numbers fold, strings concatenate, mixed types hit the honest
    gap). One sugar for every binary operator: the tree's BinOp node already
    carries its operator, so recognition is the node's; this routes the reduced
    left value to the floor method that operator names.

    Meaning-only, node-constructed. The old factory split this across a class
    per operator (each `owns` one operator_kind); here the node's `op` is the
    resolution, so the split collapses to this single dispatch.
    """

    op_kind: str
    left: Sugar
    right: Sugar
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        # `+` folds concrete numbers on the addition floor; the pair proves the
        # lift discriminates on the computed sum, not just the operands.
        prefix = "def A(z):\n    if 1 + 1 == 2:\n        return z\n    return 0\n\n"
        return _call_pair(
            name="binop_add_return",
            owner_sugar="BinOpSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(5) == 0\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        method = BINOP_METHODS[self.op_kind]
        return self.left.desugar(ctx).and_then(
            lambda left: self.right.desugar(ctx).and_then(
                lambda right: getattr(left, method)(right, self.site)
            )
        )
