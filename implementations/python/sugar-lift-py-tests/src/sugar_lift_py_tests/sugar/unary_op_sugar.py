"""A unary operation `<op> <operand>` -- `-x`, `+x`, `~x`, `not x`.

Mirrors BinOpSugar: the node carries its operator, so recognition is the node's;
this routes the reduced operand to the floor method that operator names, and the
value owns the answer (a number folds, a symbol emits `py.neg`/`py.invert`, a
type with no such floor hits its own loud gap). `not` is the one that composes
two floor verbs: Python `not x` is `not bool(x)`, so it takes the operand's
TRUTHINESS (`truth`) and negates that predicate -- never a bespoke boolean.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair

# Unary operator kind -> the floor method that owns its meaning. Every entry is
# a real FloorValue method; an operator whose value has no such floor reaches
# that value's own loud gap, never a silent default.
UNARYOP_METHODS: dict[str, str] = {
    "USub": "unary_minus",
    "UAdd": "unary_plus",
    "Invert": "bitwise_invert",
}


@dataclass(frozen=True)
class UnaryOpSugar(Sugar):
    op_kind: str
    operand: Sugar
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        # `not` composes truth+negate: `if not (z == 1)` holds exactly when z != 1.
        prefix = "def A(z):\n    if not (z == 1):\n        return z\n    return 0\n\n"
        return _call_pair(
            name="unaryop_not_return",
            owner_sugar="UnaryOpSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(5) == 0\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        operand = self.operand.desugar(ctx)
        if self.op_kind == "Not":
            # `not x` = not bool(x): take the operand's truthiness, negate it.
            return operand.and_then(lambda v: v.truth(self.site)).and_then(
                lambda predicate: predicate.negate()
            )
        method = UNARYOP_METHODS[self.op_kind]
        return operand.and_then(lambda v: getattr(v, method)(self.site))
