from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.effect import RuntimeEffect
from sugar_lift_py_tests.floor import Bv32Value, StringValue, TermValue
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witness_examples import ord_byte_return_witness
from sugar_lift_py_tests.sugar.witnesses import SugarWitnessPair


@dataclass(frozen=True)
class OrdByteSugar(Sugar, role=SugarRole.TERM, comes_before=("CallSugar",)):
    """`ord(source[index])` as a TERM -- value's byte at a fixed position, a free bv32
    var the encoder universe (str.eq-bv-blocks) constrains to that byte.

    This is the rhs of `b0 = ord(value[0])`, recomposed through the BoundVar when a
    later expression references b0. The var is named by source+index so the same byte
    is one var across the body; str.eq-bv-blocks reads the bytes in index order. The
    byte stays symbolic -- it is whatever value's i-th byte is, not a computed
    constant -- so it lifts over any input, not just a concrete one."""

    source: str
    index: int

    @classmethod
    def owns(cls, site) -> bool:
        return _is_ord_byte(site)

    @classmethod
    def witnesses(cls) -> SugarWitnessPair:
        return ord_byte_return_witness(owner_sugar=cls.__name__)

    @classmethod
    def build(cls, site, ctx) -> "OrdByteSugar":
        del ctx
        sub = site.call_args()[0]
        return cls(
            source=sub.subscript_receiver().name_id(),
            index=sub.subscript_index().literal_value(),
        )

    def desugar(self, ctx) -> Outcome:
        binding = ctx.temporal.value_outcome_for(self.source)
        if isinstance(binding, Complete) and isinstance(binding.value, StringValue):
            if 0 <= self.index < len(binding.value.value):
                return Complete(TermValue(ord(binding.value.value[self.index])))
            return Incomplete(
                RuntimeEffect(
                    "ord-byte runtime boundary: string index is out of range for "
                    f"`{self.source}[{self.index}]`; Python raises at runtime, so "
                    "keep this as a typed red until a narrower bounds proof owns "
                    f"the shape. blame={self.source}[{self.index}]"
                )
            )
        # Symbolic body support: the encoder universe constrains this byte var.
        return Complete(Bv32Value(make_var(f"byte_{self.source}_{self.index}")))


def _is_ord_byte(site) -> bool:
    if site.observed != "Call":
        return False
    if site.call_is_method_call():
        return False
    if site.call_target_name() != "ord":
        return False
    if site.call_has_keywords() or site.call_arg_count() != 1:
        return False
    sub = site.call_args()[0]
    if sub.observed != "Subscript":
        return False
    if sub.subscript_receiver().observed != "Name":
        return False
    idx = sub.subscript_index()
    return idx.observed == "PrimitiveLiteral" and isinstance(idx.literal_value(), int)
