"""The dig CONSTRUCTS a numeric simple body by slamming it to the floor.

`def g(x): return x + 1` asserted at `g(5)` is curried over 5 and reduced through the
catalog -- a climb up the sugar tower whose arithmetic floor delegates to Python's own
operators -- and the value `6` is yanked back down. We swear `call:g(5) == 6`, a fact we
COMPUTED, under the same #euf# key as the vendor's assertion. Agreement discharges; a vendor
lie (`g(5) == 99`) lands `==99` and `==6` under one key, so the contradiction is in the
contracts -- which the symbolic universe could never catch (it left `+` uninterpreted and
waved the lie through).

Leak-impossible by construction: we never model Python's `+`, we ask it. The constructed
value equals Python's own `eval` for every case, because it IS Python's `+`. (Bodies that do
NOT reach a single literal -- a symbolic arg, an unfoldable op, a runtime effect that makes
the tower unclimbable -- defer to the symbolic universe / the mouth; that residual stays
honest, it just isn't this file's subject.)
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report


def _assertion_invs(src):
    rep = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    return [c.inv for c in rep.payload.ir if c.name.endswith("::assertion")]


@pytest.mark.parametrize(
    "body,arg,expected",
    [
        ("return x", 5, 5),
        ("return x + 1", 5, 6),
        ("return x * 2", 5, 10),
        ("return (x + 1) * 2", 5, 12),
    ],
)
def test_numeric_body_constructs_the_python_value(body, arg, expected):
    # Python is the reference: its own `eval` proves the value we expect is the value Python
    # computes -- and the lift below gets it the same way (the catalog's fold IS Python's).
    assert eval(body.removeprefix("return "), {"x": arg}) == expected  # noqa: S307
    invs = _assertion_invs(
        f"def g(x):\n    {body}\ndef t():\n    assert g({arg}) == {expected}\n"
    )
    # the vendor fact and the constructed fact -- both the #euf# key, agreeing on the value.
    assert len(invs) == 2
    assert (
        invs[0] == invs[1]
    ), "construction must equal the vendor value when the vendor is right"


def test_a_vendor_lie_is_caught_by_the_construction():
    # g(5) is 6 by Python; the vendor swears 99. Same #euf# key, DIFFERENT values -> the
    # contradiction is present in the contracts (mint conjoins -> UNSAT). The symbolic
    # universe left `+` uninterpreted and could not catch this.
    invs = _assertion_invs(
        "def g(x):\n    return x + 1\ndef t():\n    assert g(5) == 99\n"
    )
    assert len(invs) == 2
    assert invs[0] != invs[1], "the lie (99) and the construction (6) must differ"


def test_control_flow_body_still_defers_to_the_symbolic_universe():
    # discrimination: an `if`-guard does not fold to a single literal yet, so the climb stops
    # short and defers -- the symbolic universe is preserved, byte-for-byte unchanged.
    rep = build_literal_call_report(
        source="def f(x):\n    if x > 0:\n        return 1\n    return 0\ndef t():\n    assert f(5) == 1\n",
        filename="t.py",
        memento_file="t.py",
    )
    assert [c.name for c in rep.payload.ir] == [
        "t::f::callable",
        "f#euf#c:call:f(i:5)::assertion",
    ]
