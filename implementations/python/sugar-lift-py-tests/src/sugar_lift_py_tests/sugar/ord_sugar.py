from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarClaim, SugarRole
from sugar_lift_py_tests.floor import Bv32Value
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.outcome import Complete, Outcome


@dataclass(frozen=True)
class OrdByteSugar:
    """`ord(source[index])` as a TERM -- value's byte at a fixed position, a free bv32
    var the encoder universe (str.eq-bv-blocks) constrains to that byte.

    This is the rhs of `b0 = ord(value[0])`, recomposed through the BoundVar when a
    later expression references b0. The var is named by source+index so the same byte
    is one var across the body; str.eq-bv-blocks reads the bytes in index order. The
    byte stays symbolic -- it is whatever value's i-th byte is, not a computed
    constant -- so it lifts over any input, not just a concrete one."""

    source: str
    index: int

    def desugar(self, ctx) -> Outcome:
        del ctx  # the byte is symbolic -- a free var the universe constrains
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


def _build_ord_byte(site, ctx) -> OrdByteSugar:
    del ctx
    sub = site.call_args()[0]
    return OrdByteSugar(
        source=sub.subscript_receiver().name_id(),
        index=sub.subscript_index().literal_value(),
    )


ORD_BYTE_CLAIM = SugarClaim(
    name="OrdByteSugar",
    role=SugarRole.TERM,
    owns=_is_ord_byte,
    build=_build_ord_byte,
)
