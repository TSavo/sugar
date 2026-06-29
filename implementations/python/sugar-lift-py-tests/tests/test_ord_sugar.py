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
