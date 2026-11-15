from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import (
    ConstructedTermSugar,
    require_constructed_term_sugar,
)
from sugar_lift_py_tests.sugar.witnesses import _assertion_pair

# Binary operator kind -> the floor that owns its meaning. The value owns what
# each operation MEANS (ints fold, strings concatenate on `+`, mixed types hit
# the honest gap); this sugar only routes to it. Every entry names a binary
# floor whose explicit call is ``BINARY_FLOOR_OPERATIONS``, so an operator in
# this table always reduces or reaches the value's own loud gap -- never a
# silent default.
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
class BinOpSugar(ConstructedTermSugar):
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
    left: ConstructedTermSugar
    right: ConstructedTermSugar
    site: object = dataclass_field(compare=False)

    def __post_init__(self) -> None:
        if self.op_kind not in BINOP_METHODS:
            raise ValueError(f"unknown binary operator {self.op_kind!r}")
        require_constructed_term_sugar(self.left, owner="BinOpSugar.left")
        require_constructed_term_sugar(self.right, owner="BinOpSugar.right")

    @classmethod
    def witnesses(cls):
        # `+` folds concrete numbers on the addition floor; the pair proves the
        # lift discriminates on the computed sum, not just the operands.
        return _assertion_pair(
            name="binop_add_return",
            owner_sugar="BinOpSugar",
            statements=(
                "z = 5\n" "if 1 + 1 == 2:\n" "    out = z\n" "else:\n" "    out = 0"
            ),
            truthful="out == 5",
            lying="out == 0",
        )

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:binary-op-construction",
            (
                self.occurrence_term(owner=owner),
                str_const(self.op_kind),
                self.left.to_term(owner=owner),
                self.right.to_term(owner=owner),
            ),
            symbol_kind="coordinate",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        from sugar_lift_py_tests.floor.floor_value import BINARY_FLOOR_OPERATIONS
        from sugar_lift_py_tests.floor.named_expression_value import (
            consume_operands,
            evaluated_after,
            written_by,
        )

        # The floor's own explicit call (#7757), never a method looked up by
        # its name.
        operate = BINARY_FLOOR_OPERATIONS[BINOP_METHODS[self.op_kind]]

        # Both sides are operands: a walrus in either (``(x := 5) + 1``) binds
        # once, through the one operand door.  The right side is evaluated
        # after the left, with the left's writes applied, and its halt
        # carries them (``evaluated_after``).
        def apply(left, right):
            return operate(
                left.project_operation_receiver(
                    ctx, owner="BinOpSugar left operation receiver"
                ),
                right.project_operation_receiver(
                    ctx, owner="BinOpSugar right operation receiver"
                ),
                self.site,
                ctx,
            )

        return self.left.desugar(ctx).and_then(
            lambda left: evaluated_after(
                (left,), self.right, written_by(left, ctx)
            ).and_then(
                lambda right: consume_operands(apply, left, right)
            )
        )
