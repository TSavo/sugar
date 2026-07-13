from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class AnnotationUnionSugar(Sugar, role=SugarRole.TERM):
    """A PEP 604 ``|`` whose source position is a Python annotation.

    Runtime ``|`` remains owned by ``RuntimeBitwiseOpSugar``. This owner closes
    the other half of that syntax partition and cites the same native operator
    coordinate over its factory-built type operands.
    """

    left: SugarBody
    right: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return (
            site.observed == "BinOp"
            and site.operator_kind() == "BitOr"
            and site.source is not None
            and site.is_within_annotation()
        )

    @classmethod
    def new(cls, site, ctx) -> "AnnotationUnionSugar":
        return cls(
            left=ctx.build_body(site.binop_left(), SugarRole.TERM),
            right=ctx.build_body(site.binop_right(), SugarRole.TERM),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        prefix = "def A(value: int | str):\n    return value\n\n"
        return _call_pair(
            name="annotation_union_parameter",
            owner_sugar="AnnotationUnionSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(5) == 6\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return self.left.reduce(ctx).and_then(
            lambda left: self.right.reduce(ctx).and_then(
                lambda right: left.bitwise_or(right, self.site)
            )
        )

    def walk_children(self):
        return (self.left, self.right)
