from __future__ import annotations

import ast
from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarClaim, SugarRole
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.outcome import Complete, Outcome, complete_value
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class BinOpSugar:
    operator: str
    left: SugarBody
    right: SugarBody
    blame: str

    @classmethod
    def from_site(cls, site, ctx) -> "BinOpSugar | None":
        if not isinstance(site.node, ast.BinOp):
            return None
        if not isinstance(site.node.op, ast.Add):
            return None
        return cls(
            operator="+",
            left=ctx.build_body(site.node.left, SugarRole.TERM),
            right=ctx.build_body(site.node.right, SugarRole.TERM),
            blame=site.blame,
        )

    def desugar(self, ctx) -> Outcome:
        left = complete_value(self.left.reduce(ctx), owner="BinOpSugar left")
        right = complete_value(self.right.reduce(ctx), owner="BinOpSugar right")
        if not isinstance(left, TermValue) or not isinstance(right, TermValue):
            raise TypeError("BinOpSugar + requires TermValue operands")
        return Complete(TermValue(left.value + right.value))


def _owns(site) -> bool:
    return isinstance(site.node, ast.BinOp) and isinstance(site.node.op, ast.Add)


def _build(site, ctx) -> BinOpSugar:
    sugar = BinOpSugar.from_site(site, ctx)
    if sugar is None:
        raise TypeError("BinOpSugar claim built a non-addition")
    return sugar


BINOP_CLAIM = SugarClaim(
    name="BinOpSugar",
    role=SugarRole.TERM,
    owns=_owns,
    build=_build,
)
