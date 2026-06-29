"""The callsite-equality EXPECTED value composes through the factory's literal
sugars (string, int, ...) -- no string-only special case. A shape the catalog
can't build panics via its own mouth, naming the next sugar."""
from __future__ import annotations

import ast

import pytest

from sugar_lift_py_tests.canonicalizer import encode_jcs
from sugar_lift_py_tests.factory import FactoryGap
from sugar_lift_py_tests.factory.literal_call_report import (
    _lift_literal_via_factory,
    build_literal_call_report,
)
from sugar_lift_py_tests.ir import num, str_const, term_to_value


def _enc(term) -> str:
    return encode_jcs(term_to_value(term))


def _term(expr: str):
    return _lift_literal_via_factory(ast.parse(expr, mode="eval").body, "t.py")


def test_expected_int_and_str_lift_through_the_catalog():
    assert _enc(_term("5")) == _enc(num(5))
    assert _enc(_term("'abc'")) == _enc(str_const("abc"))


def test_flat_list_arg_composes_through_the_factory():
    # a flat list arg keys the callsite as `array(...)` -- composed via the
    # catalog's ArrayLiteral sugar, not a string special case.
    rep = build_literal_call_report(
        source="import numpy as np\ndef t():\n    assert np.cumsum([1, 2, 3]) == 6\n",
        filename="t.py",
        memento_file="t.py",
    )
    euf = [c.name for c in rep.payload.ir if "euf" in c.name]
    assert euf == ["cumsum#euf#c:call:cumsum(c:array(i:1,i:2,i:3))::assertion"]


def test_numeric_expected_advances_panic_past_the_expected():
    # `== 5` no longer panics on the expected; a FLAT list arg composes through the
    # factory, and a NESTED array is the next shape the mouth names (cleanly, not a
    # crash) -- the worklist moving forward.
    with pytest.raises(FactoryGap) as raised:
        build_literal_call_report(
            source="import numpy as np\ndef t():\n    assert np.rot90([[1,2],[3,4]]) == 5\n",
            filename="t.py",
            memento_file="t.py",
        )
    assert raised.value.info.get("observed") == "callsite-arg:List-unliftable"
