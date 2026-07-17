from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class MatrixMultiplyOpSugar(Sugar, role=SugarRole.TERM):
    """The native Python ``@`` operator dispatched through its floor."""

    left: SugarBody
    right: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "BinOp" and site.operator_kind() == "MatMult"

    @classmethod
    def new(cls, site, ctx) -> "MatrixMultiplyOpSugar":
        return cls(
            left=ctx.build_body(site.binop_left(), SugarRole.TERM),
            right=ctx.build_body(site.binop_right(), SugarRole.TERM),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        # Scalar int @ int is TypeError at runtime; the sat/unsat twin rides
        # an object with a diggable __matmul__ body (same shape as
        # divmod_dunder_return / format_dunder_return). Free symbolic @
        # still constructs the native "@" coordinate on SymbolicValue.
        prefix = (
            "class Box:\n"
            "    def __matmul__(self, other):\n"
            "        return 6\n"
            "\n"
            "def A():\n"
            "    return Box() @ Box()\n"
            "\n"
        )
        return _call_pair(
            name="matrix_multiply_return",
            owner_sugar="MatrixMultiplyOpSugar",
            truthful=prefix + "def test_a():\n    assert A() == 6\n",
            lying=prefix + "def test_a():\n    assert A() == 7\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return self.left.reduce(ctx).and_then(
            lambda left: self.right.reduce(ctx).and_then(
                lambda right: left.matrix_multiply(right, self.site)
            )
        )

    def walk_children(self):
        return (self.left, self.right)
