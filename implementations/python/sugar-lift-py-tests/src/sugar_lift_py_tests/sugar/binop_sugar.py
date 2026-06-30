from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import EncodedStringValue, TermValue
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome, complete_value
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar_body import SugarBody


# The arithmetic operators BinOpSugar folds over the collapsed Number (TermValue),
# AST-kind -> symbol -> fold. Add also concatenates encoded strings (below). Div ('/') is
# Python true-division (Real): 6/2 == 3.0, and the numeric type is collapsed so the result
# is just a Number. Division by zero is NOT a value -- Python raises -- so it is a runtime
# EFFECT: `Incomplete(DivByZeroEffect)`, the third leg of the Outcome algebra.
_SYMBOL: dict[str, str] = {
    "Add": "+",
    "Sub": "-",
    "Mult": "*",
    "Div": "/",
    "FloorDiv": "//",
    "Mod": "%",
    "Pow": "**",
}
_FOLD = {
    "+": lambda a, b: a + b,
    "-": lambda a, b: a - b,
    "*": lambda a, b: a * b,
    "/": lambda a, b: a / b,
    "//": lambda a, b: a // b,
    "%": lambda a, b: a % b,
    "**": lambda a, b: a ** b,
}

# Operators whose divisor of 0 is a runtime effect (Python raises), not a value.
_DIVIDES = {"/", "//", "%"}


@dataclass(frozen=True)
class BinOpSugar(Sugar, role=SugarRole.TERM):
    operator: str
    left: SugarBody
    right: SugarBody
    blame: str

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "BinOp" and site.operator_kind() in _SYMBOL

    @classmethod
    def build(cls, site, ctx) -> "BinOpSugar":
        sugar = cls.from_site(
            site,
            left=ctx.build_body(site.binop_left(), SugarRole.TERM),
            right=ctx.build_body(site.binop_right(), SugarRole.TERM),
        )
        if sugar is None:
            raise TypeError("BinOpSugar claim built a non-arithmetic binop")
        return sugar

    @classmethod
    def from_site(
        cls, site, *, left: SugarBody, right: SugarBody
    ) -> "BinOpSugar | None":
        if site.observed != "BinOp" or site.operator_kind() not in _SYMBOL:
            return None
        return cls(
            operator=_SYMBOL[site.operator_kind()],
            left=left,
            right=right,
            blame=site.blame,
        )

    def desugar(self, ctx) -> Outcome:
        # match each operand: an Incomplete (a runtime effect) bubbles upward unchanged.
        left_outcome = self.left.reduce(ctx)
        if isinstance(left_outcome, Incomplete):
            return left_outcome
        right_outcome = self.right.reduce(ctx)
        if isinstance(right_outcome, Incomplete):
            return right_outcome
        left = complete_value(left_outcome, owner="BinOpSugar left")
        right = complete_value(right_outcome, owner="BinOpSugar right")
        if isinstance(left, EncodedStringValue) and isinstance(right, EncodedStringValue):
            if self.operator != "+":
                raise TypeError("BinOpSugar only concatenates encoded strings with +")
            if left.table != right.table:
                raise TypeError("BinOpSugar + concatenates encoded strings over one table")
            return Complete(
                EncodedStringValue(table=left.table, indices=left.indices + right.indices)
            )
        if isinstance(left, TermValue) and isinstance(right, TermValue):
            if self.operator in _DIVIDES and right.value == 0:
                # `a / 0` RAISES at runtime -- it warrants no value, and the line after it
                # never executes, so this effect halts all downstream constraint
                # propagation. It is Incomplete, not a value and not a refusal.
                return Incomplete(
                    f"division by zero (`{self.operator}` by 0): a runtime DivByZero "
                    f"effect that raises and stops constraint propagation"
                )
            return Complete(TermValue(_FOLD[self.operator](left.value, right.value)))
        raise TypeError(
            f"BinOpSugar {self.operator} requires TermValue or EncodedStringValue operands"
        )


from sugar_lift_py_tests.sugar.sugar_base import registered_claims as _rc  # noqa: E402
BINOP_CLAIM = next(c for c in _rc() if c.name == "BinOpSugar")
