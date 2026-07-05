"""LHS-as-term: a call behind a binding lifts IDENTICALLY to the direct call.

CALLSUGAR_REFACTOR_GOAL.md Step 5 -- the normalization invariant. ``x = f(5); assert x == 1``
and ``assert f(5) == 1`` are the same dance in different clothes: the binding is transparent,
the bridge ``call:f(5)`` falls out wherever the call appears. They MUST emit the same #euf#
name AND inv, or the join silently splits (a bound assertion lands in a different universe
than the direct one, the contradiction is never computed, green proof that lies).

The resolution is syntactic and narrow on purpose: ONLY a call RHS substitutes. A non-call
binding stays a Name and becomes typed red -- the over-reach (substituting a literal binding
and mis-lifting `assert x == 5`) is the bug this discrimination test forbids.
"""

from __future__ import annotations

from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report

# A control-flow callee the dig can actually walk (a passthrough `return x` hits the
# encoder-only simple-body limitation -- orthogonal to the binding transparency under test).
_F = "def f(x):\n    if x > 0:\n        return 1\n    return 0\n"


def _contracts(src):
    rep = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    return [(c.name, c.inv) for c in rep.payload.ir]


# --- positive: the binding is transparent -----------------------------------------------


def test_bound_call_lifts_identically_to_the_direct_call():
    bound = _contracts(_F + "def t():\n    x = f(5)\n    assert x == 1\n")
    direct = _contracts(_F + "def t():\n    assert f(5) == 1\n")
    assert (
        bound == direct
    ), f"binding changed the euf form:\n  bound ={bound}\n  direct={direct}"


# --- discrimination: a non-call binding does NOT get substituted (no over-reach) ---------


def test_a_literal_binding_is_not_a_call_and_stays_typed_red():
    # x is bound to `5` (not a call), so the LHS stays a Name -> the assertion is not a
    # `call(...) == literal` shape -> typed runtime effect, never a silent mis-lift.
    report = build_literal_call_report(
        source="def t():\n    x = 5\n    assert x == 5\n",
        filename="t.py",
        memento_file="t.py",
    )

    assert report.payload.ir == []
    assert len(report.payload.effects) == 1
    assert "bound-name equality runtime boundary" in (
        report.payload.effects[0].effect.reason
    )


# --- structural: an unbound name (no assign at all) stays typed red, not green -----------


def test_an_unbound_name_lhs_stays_typed_red():
    report = build_literal_call_report(
        source="def t():\n    assert x == 5\n",
        filename="t.py",
        memento_file="t.py",
    )

    assert report.payload.ir == []
    assert len(report.payload.effects) == 1
    assert "literal-call equality runtime boundary" in (
        report.payload.effects[0].effect.reason
    )
