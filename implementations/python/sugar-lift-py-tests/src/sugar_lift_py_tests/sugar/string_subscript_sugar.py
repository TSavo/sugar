from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.operations import SubscriptOperation, perform_operation
from sugar_lift_py_tests.outcome import Incomplete, Outcome, complete_value
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witness_examples import string_subscript_return_witness
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
    def witnesses(cls):
        return string_subscript_return_witness()

    @classmethod
    def from_site(
        cls, site, *, receiver: SugarBody, index: SugarBody, blame: str
    ) -> "StringSubscriptSugar | None":
        if site.observed != "Subscript":
            return None
        return cls(receiver=receiver, index=index, blame=blame)

    def _build(self, ctx=None) -> Outcome:
        receiver_outcome = self.receiver.reduce(ctx)
        if isinstance(receiver_outcome, Incomplete):
            return receiver_outcome
        receiver = complete_value(
            receiver_outcome, owner="StringSubscriptSugar receiver"
        )
        index_outcome = self.index.reduce(ctx)
        if isinstance(index_outcome, Incomplete):
            return index_outcome
        index = complete_value(index_outcome, owner="StringSubscriptSugar index")
        operation = SubscriptOperation(
            index=index,
            owner="StringSubscriptSugar",
            blame=self.blame,
        )
        return perform_operation(
            owner="StringSubscriptSugar",
            blame=self.blame,
            receiver=receiver,
            operation=operation,
            ctx=ctx,
        )
