from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import EncodedStringValue, TermValue
from sugar_lift_py_tests.outcome import Complete, Outcome, complete_value
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar_body import SugarBody


# The INTEGER-arithmetic operators BinOpSugar folds, AST-kind -> symbol -> fold (over
# Int-sorted TermValue). Add also concatenates encoded strings (below). Div ('/') is
# DELIBERATELY ABSENT: Python true-division yields a FLOAT (6/2 == 3.0), and floats are
# residual -- not modeled, because `3.0 == 3` is Python-true so asserting `float != int`
# would be a false distinctness (see literal_encoding.rs). So `/` is refused, not folded.
_SYMBOL: dict[str, str] = {
    "Add": "+",
    "Sub": "-",
    "Mult": "*",
    "FloorDiv": "//",
    "Mod": "%",
    "Pow": "**",
}
_FOLD = {
    "+": lambda a, b: a + b,
    "-": lambda a, b: a - b,
    "*": lambda a, b: a * b,
    "//": lambda a, b: a // b,
    "%": lambda a, b: a % b,
    "**": lambda a, b: a ** b,
}


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
        left = complete_value(self.left.reduce(ctx), owner="BinOpSugar left")
        right = complete_value(self.right.reduce(ctx), owner="BinOpSugar right")
        if isinstance(left, EncodedStringValue) and isinstance(right, EncodedStringValue):
            if self.operator != "+":
                raise TypeError("BinOpSugar only concatenates encoded strings with +")
            if left.table != right.table:
                raise TypeError("BinOpSugar + concatenates encoded strings over one table")
            return Complete(
                EncodedStringValue(table=left.table, indices=left.indices + right.indices)
            )
        if isinstance(left, TermValue) and isinstance(right, TermValue):
            return Complete(TermValue(_FOLD[self.operator](left.value, right.value)))
        raise TypeError(
            f"BinOpSugar {self.operator} requires TermValue or EncodedStringValue operands"
        )


from sugar_lift_py_tests.sugar.sugar_base import registered_claims as _rc  # noqa: E402
BINOP_CLAIM = next(c for c in _rc() if c.name == "BinOpSugar")
