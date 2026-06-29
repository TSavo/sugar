"""OrdSugar recognizes `target = ord(source[index])` -- a byte extracted from the
input at a fixed position. That recognition is what binds the byte variable the
encoder universe constrains; a non-`ord` assignment is not its shape."""
from __future__ import annotations

import ast

from sugar_lift_py_tests.factory import SourceSite
from sugar_lift_py_tests.sugar.ord_sugar import OrdSugar


def _from(stmt_src: str, source_name: str):
    stmt = ast.parse(stmt_src).body[0]
    return OrdSugar.from_site(SourceSite.from_node(stmt, "t.py"), source_name=source_name)


def test_ord_recognizes_byte_extraction_at_index():
    assert _from("b0 = ord(value[0])", "value") == OrdSugar(
        target="b0", source_name="value", index=0
    )
    assert _from("b2 = ord(value[2])", "value") == OrdSugar(
        target="b2", source_name="value", index=2
    )


def test_non_ord_assignment_is_not_an_ord_byte():
    assert _from("t = value[0]", "value") is None
    assert _from('t = "ABC"', "value") is None


def test_symbolic_ord_call_is_a_free_byte_var():
    # `ord(value[i])` as a TERM (the rhs of `b0 = ord(value[0])`, recomposed through
    # the BoundVar) is a free bv32 byte var. str.eq-bv-blocks constrains it to value's
    # byte i; it is named by source+index so the same byte is the same var.
    from factory_reduce import reduce_value

    from sugar_lift_py_tests.floor import Bv32Value
    from sugar_lift_py_tests.ir import make_var

    assert reduce_value("ord(value[0])") == Bv32Value(make_var("byte_value_0"))
    assert reduce_value("ord(value[2])") == Bv32Value(make_var("byte_value_2"))
