"""Transitive construction: a bridge enqueues its dig, the chain composes, no call: dangles.

`g` returns `h(x)`, `h` returns `x+1`. The dig queue follows g's bridge to h -- g's tower swears
`call:g(5) == call:h(5)` (the bridge, h NOT inlined), h's tower swears `call:h(5) == 6`. Every
`call:` symbol a tower references is DEFINED by another tower, so no bridge dangles (`Absent`)
and the EUF chain closes: `call:g(5) == call:h(5) == 6`. Cycle-guarded by the #euf# key, so a
self-call stops at the fixpoint instead of digging forever.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.factory import factory_panic
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
        out.setdefault(lhs, []).append(
            rhs.get("name") if rhs.get("kind") == "ctor" else rhs.get("value")
        )
    return out


def test_chain_emits_a_tower_per_hop_and_no_bridge_dangles():
    facts = _facts(_CHAIN + "def t():\n    assert g(5) == 6\n")
    assert "call:h" in facts["call:g"]  # g BRIDGES to h (a pointer, not h inlined)
    assert 6 in facts["call:g"]  # the vendor's sworn value
    assert facts["call:h"] == [6]  # h's tower DEFINES call:h -> the bridge resolves
    # every call: a tower references is itself defined by a tower (no Absent / dangling symbol):
    referenced = {
        v
        for vs in facts.values()
        for v in vs
        if isinstance(v, str) and v.startswith("call:")
    }
    assert referenced <= set(
        facts.keys()
    ), f"dangling bridge(s): {referenced - set(facts)}"


def test_self_recursion_emits_an_honest_universe_never_hangs():
    # f calls f: the build-stack guard prevents the hang (no RecursionError). The universe is
    # HONEST -- `out == call:f(x)`, f really does return f(x) -- and f(5)'s VALUE is axiomatic:
    # an infinite recursion is not finitely constructible, so it is the vendor's word
    # (stated > derived), constrained by nothing the kit can refute. No hang, no false discharge.
    rep = build_literal_call_report(
        source="def f(x):\n    return f(x)\ndef t():\n    assert f(5) == 5\n",
        filename="t.py",
        memento_file="t.py",
    )
    assert "t::f::callable" in [c.name for c in rep.payload.ir]


def test_a_lie_through_the_chain_is_present_in_the_contracts():
    facts = _facts(_CHAIN + "def t():\n    assert g(5) == 99\n")
    assert "call:h" in facts["call:g"] and 99 in facts["call:g"]
    assert facts["call:h"] == [
        6
    ]  # construction says 6; mint sees 6 vs 99 under the chain -> UNSAT


def test_multi_hop_chain_composes_every_call_backed_by_a_tower():
    # f -> g -> h -> literal. Each hop bridges to the next; the leaf constructs. The EUF chain
    # call:f == call:g == call:h == 10 closes, and EVERY call: is defined by a tower.
    src = (
        "def h(x):\n    return x * 2\ndef g(x):\n    return h(x)\ndef f(x):\n    return g(x)\n"
        "def t():\n    assert f(5) == 10\n"
    )
    facts = _facts(src)
    assert facts["call:h"] == [10]
    assert "call:g" in facts["call:f"] and "call:h" in facts["call:g"]
    referenced = {
        v
        for vs in facts.values()
        for v in vs
        if isinstance(v, str) and v.startswith("call:")
    }
    assert referenced <= set(
        facts.keys()
    ), f"dangling bridge(s): {referenced - set(facts)}"


def test_unresolved_callee_is_axiomatic_not_a_crash():
    # `foo` has no body and no import: it cannot be dug. Its bridge stays the vendor's AXIOM
    # (an external function's result is stated, not derivable) -- a tower we never had, not a
    # dangling one we dropped. No crash, no fabricated tower.
    facts = _facts("def t():\n    assert foo(5) == 6\n")
    assert facts["call:foo"] == [6]
