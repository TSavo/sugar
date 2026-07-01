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
    # A flat list arg keys the callsite as `array(...)` -- composed via the catalog's
    # ArrayLiteral sugar, not a string special case. The callee is unresolvable (no
    # import, no local def), so only the fact is lifted -- isolating the arg keying.
    rep = build_literal_call_report(
        source="def t():\n    assert aggregate([1, 2, 3]) == 6\n",
        filename="t.py",
        memento_file="t.py",
    )
    euf = [c.name for c in rep.payload.ir if "euf" in c.name]
    assert euf == ["aggregate#euf#c:call:aggregate(c:array(i:1,i:2,i:3))::assertion"]


def test_bound_literal_arg_replays_prior_assignment_before_callsite_fact():
    rep = build_literal_call_report(
        source="def t():\n    value = 1\n    assert f(value) == 2\n",
        filename="t.py",
        memento_file="t.py",
    )

    euf = [c.name for c in rep.payload.ir if "euf" in c.name]
    assert euf == ["f#euf#c:call:f(i:1)::assertion"]


def test_bound_arg_replays_transitive_prior_assignment_dependencies():
    rep = build_literal_call_report(
        source=(
            "def t():\n"
            "    base = 1\n"
            "    value = base\n"
            "    assert f(value) == 2\n"
        ),
        filename="t.py",
        memento_file="t.py",
    )

    euf = [c.name for c in rep.payload.ir if "euf" in c.name]
    assert euf == ["f#euf#c:call:f(i:1)::assertion"]


def test_numeric_expected_and_nested_array_arg_are_handled_panic_is_downstream():
    # For `np.rot90([[1,2],[3,4]]) == 5` the numeric expected AND the nested-array
    # arg both compose through the factory now. Any remaining panic is DOWNSTREAM
    # (the dig of numpy's imported source), never the expected or the args -- the
    # worklist has moved past the callsite shape and into the body.
    with pytest.raises(FactoryGap) as raised:
        build_literal_call_report(
            source="import numpy as np\ndef t():\n    assert np.rot90([[1,2],[3,4]]) == 5\n",
            filename="t.py",
            memento_file="t.py",
        )
    observed = raised.value.info.get("observed", "")
    assert observed != "callsite-expected:Constant"
    assert not observed.startswith("callsite-arg")
