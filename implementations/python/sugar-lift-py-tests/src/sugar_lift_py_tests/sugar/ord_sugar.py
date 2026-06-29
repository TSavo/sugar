from __future__ import annotations

import ast
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
    node = site.node
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
        return False
    if node.func.id != "ord" or node.keywords or len(node.args) != 1:
        return False
    sub = node.args[0]
    return (
        isinstance(sub, ast.Subscript)
        and isinstance(sub.value, ast.Name)
        and isinstance(sub.slice, ast.Constant)
        and isinstance(sub.slice.value, int)
    )


def _build_ord_byte(site, ctx) -> OrdByteSugar:
    del ctx
    sub = site.node.args[0]
    return OrdByteSugar(source=sub.value.id, index=sub.slice.value)


ORD_BYTE_CLAIM = SugarClaim(
    name="OrdByteSugar",
    role=SugarRole.TERM,
    owns=_is_ord_byte,
    build=_build_ord_byte,
)
