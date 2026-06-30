"""Transitive construction: a bridge enqueues its dig, the chain composes, no call: dangles.

`g` returns `h(x)`, `h` returns `x+1`. The dig queue follows g's bridge to h -- g's tower swears
`call:g(5) == call:h(5)` (the bridge, h NOT inlined), h's tower swears `call:h(5) == 6`. Every
`call:` symbol a tower references is DEFINED by another tower, so no bridge dangles (`Absent`)
and the EUF chain closes: `call:g(5) == call:h(5) == 6`. Cycle-guarded by the #euf# key, so a
self-call stops at the fixpoint instead of digging forever.
"""
from __future__ import annotations

import pytest

from sugar_lift_py_tests.factory import FactoryGap
from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report

_CHAIN = "def h(x):\n    return x + 1\ndef g(x):\n    return h(x)\n"


def _facts(src):
    """{lhs symbol -> [rhs values]} over the ::assertion towers (rhs is a literal or a call:)."""
    rep = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    out: dict[str, list] = {}
    for c in rep.payload.ir:
        if not c.name.endswith("::assertion"):
            continue
        lhs = c.inv["args"][0].get("name")
        rhs = c.inv["args"][1]
        out.setdefault(lhs, []).append(rhs.get("name") if rhs.get("kind") == "ctor" else rhs.get("value"))
    return out


def test_chain_emits_a_tower_per_hop_and_no_bridge_dangles():
    facts = _facts(_CHAIN + "def t():\n    assert g(5) == 6\n")
    assert "call:h" in facts["call:g"]   # g BRIDGES to h (a pointer, not h inlined)
    assert 6 in facts["call:g"]          # the vendor's sworn value
    assert facts["call:h"] == [6]        # h's tower DEFINES call:h -> the bridge resolves
    # every call: a tower references is itself defined by a tower (no Absent / dangling symbol):
    referenced = {
        v for vs in facts.values() for v in vs if isinstance(v, str) and v.startswith("call:")
    }
    assert referenced <= set(facts.keys()), f"dangling bridge(s): {referenced - set(facts)}"


def test_self_recursion_refuses_cleanly_never_hangs():
    # f calls f: an infinite recursion is not finitely constructible. The build-stack guard
    # turns the cycle into a clean, NAMED refusal (a FactoryGap with blame) instead of a
    # RecursionError -- the lifter never hangs, and the non-constructible tower is not faked.
    with pytest.raises(FactoryGap):
        build_literal_call_report(
            source="def f(x):\n    return f(x)\ndef t():\n    assert f(5) == 5\n",
            filename="t.py",
            memento_file="t.py",
        )


def test_a_lie_through_the_chain_is_present_in_the_contracts():
    facts = _facts(_CHAIN + "def t():\n    assert g(5) == 99\n")
    assert "call:h" in facts["call:g"] and 99 in facts["call:g"]
    assert facts["call:h"] == [6]  # construction says 6; mint sees 6 vs 99 under the chain -> UNSAT
