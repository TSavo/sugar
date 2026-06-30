from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarClaim, SugarRole
from sugar_lift_py_tests.factory.sugar_constructors import build_binop_sugar
from sugar_lift_py_tests.floor import EncodedStringValue, TermValue
from sugar_lift_py_tests.outcome import Complete, Outcome, complete_value
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class BinOpSugar:
    operator: str
    left: SugarBody
    right: SugarBody
    blame: str

    @classmethod
    def from_site(
        cls, site, *, left: SugarBody, right: SugarBody
    ) -> "BinOpSugar | None":
        if site.observed != "BinOp":
            return None
        if site.operator_kind() != "Add":
            return None
        return cls(
            operator="+",
            left=left,
            right=right,
            blame=site.blame,
        )

    def desugar(self, ctx) -> Outcome:
        left = complete_value(self.left.reduce(ctx), owner="BinOpSugar left")
        right = complete_value(self.right.reduce(ctx), owner="BinOpSugar right")
        if isinstance(left, EncodedStringValue) and isinstance(right, EncodedStringValue):
            if left.table != right.table:
                raise TypeError("BinOpSugar + concatenates encoded strings over one table")
            return Complete(
                EncodedStringValue(table=left.table, indices=left.indices + right.indices)
            )
        if isinstance(left, TermValue) and isinstance(right, TermValue):
            return Complete(TermValue(left.value + right.value))
        raise TypeError("BinOpSugar + requires TermValue or EncodedStringValue operands")


def _owns(site) -> bool:
    return site.observed == "BinOp" and site.operator_kind() == "Add"


BINOP_CLAIM = SugarClaim(
    name="BinOpSugar",
    role=SugarRole.TERM,
    owns=_owns,
    build=build_binop_sugar,
)
