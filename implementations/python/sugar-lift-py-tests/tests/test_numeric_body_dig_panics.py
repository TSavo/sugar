"""The dig must REFUSE a body it cannot walk -- through the mouth, never a raw crash.

The dig handles control-flow and encoder bodies. A unary function with a numeric simple
body (`return <numeric expr>`) is not covered yet -- and "not covered" must mean a NAMED
FactoryGap with blame (file:line, the missing sugar), not a bare ValueError escaping from
deep in BridgeStrategy. A raw ValueError is an uncontrolled crash: it doesn't name the AST
shape, doesn't name the missing sugar, and reads to a caller as a bug, not an honest floor.

`assert g(5) == 6` over `def g(x): return x + 1` is the canonical case (and the numpy
blocker: numpy reductions are numeric simple bodies). Until the numeric body dig exists,
this MUST panic clean.
"""
from __future__ import annotations

import pytest

from sugar_lift_py_tests.factory import FactoryGap
from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report


@pytest.mark.parametrize(
    "body",
    ["    return x\n", "    return x + 1\n", "    return x * 2\n"],
)
def test_numeric_simple_body_refuses_through_the_mouth_not_a_raw_valueerror(body):
    src = f"def g(x):\n{body}def t():\n    assert g(5) == 5\n"
    with pytest.raises(FactoryGap) as raised:
        build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    # the gap is NAMED and carries blame -- the mouth spoke, the floor is honest
    assert raised.value.info.get("blame")
    assert raised.value.info.get("fix")


def test_control_flow_body_still_digs_clean():
    # the discrimination case: a body the dig DOES handle is unaffected by the new mouth.
    rep = build_literal_call_report(
        source="def f(x):\n    if x > 0:\n        return 1\n    return 0\ndef t():\n    assert f(5) == 1\n",
        filename="t.py",
        memento_file="t.py",
    )
    assert [c.name for c in rep.payload.ir] == [
        "t::f::callable",
        "f#euf#c:call:f(i:5)::assertion",
    ]
