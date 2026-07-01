from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory import (
    FactoryAuditRow,
    FactoryGap,
    FactoryGapInfo,
)
from sugar_lift_py_tests.operations import SubscriptOperation
from sugar_lift_py_tests.outcome import Outcome, complete_value
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class StringSubscriptSugar(Sugar, role=SugarRole.TERM):
    """`table[index]` -- index a string-valued receiver by a BV term.

    The receiver reduces to the constant table; the index reduces to a BV term.
    The result is one output character: table[index]. Composed under `+`
    (BinOpSugar) it grows into the full encoded string. No value is computed --
    the (table, index-term) pair IS the per-character constraint."""

    receiver: SugarBody
    index: SugarBody
    blame: str

    def __post_init__(self) -> None:
        if not isinstance(self.receiver, SugarBody):
            raise TypeError("StringSubscriptSugar receiver must be factory-built")
        if not isinstance(self.index, SugarBody):
            raise TypeError("StringSubscriptSugar index must be factory-built")

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "Subscript"

    @classmethod
    def build(cls, site, ctx) -> "StringSubscriptSugar":
        sugar = cls.from_site(
            site,
            receiver=ctx.build_body(site.subscript_receiver(), SugarRole.TERM),
            index=ctx.build_body(site.subscript_index(), SugarRole.TERM),
            blame=site.blame,
        )
        if sugar is None:
            raise TypeError("StringSubscriptSugar claim built a non-subscript")
        return sugar

    @classmethod
    def from_site(
        cls, site, *, receiver: SugarBody, index: SugarBody, blame: str
    ) -> "StringSubscriptSugar | None":
        if site.observed != "Subscript":
            return None
        return cls(receiver=receiver, index=index, blame=blame)

    def desugar(self, ctx=None) -> Outcome:
        receiver = complete_value(
            self.receiver.reduce(ctx), owner="StringSubscriptSugar receiver"
        )
        index = complete_value(
            self.index.reduce(ctx), owner="StringSubscriptSugar index"
        )
        operation = SubscriptOperation(
            index=index,
            owner="StringSubscriptSugar",
            blame=self.blame,
        )
        return _perform_subscript(
            receiver=receiver,
            operation=operation,
            blame=self.blame,
            ctx=ctx,
        )


def _perform_subscript(*, receiver, operation: SubscriptOperation, blame: str, ctx):
    method = getattr(receiver, "subscript_with", None)
    if method is None:
        info = FactoryGapInfo(
            owner="StringSubscriptSugar",
            blame=blame,
            observed=type(receiver).__name__,
            requested="subscript_with",
            fix=f"add subscript_with to {type(receiver).__name__}",
            gap_kind="Floor",
            gap_locus="construction",
        )
        raise FactoryGap(
            info,
            FactoryAuditRow(
                role="subscript_with",
                status="floor-gap",
                observed=type(receiver).__name__,
                blame=blame,
                selected=None,
                candidates=[],
                message=info.message,
            ),
        )
    return method(operation, ctx)
