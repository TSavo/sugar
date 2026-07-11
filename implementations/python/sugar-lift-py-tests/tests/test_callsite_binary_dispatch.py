# SPDX-License-Identifier: MIT OR Apache-2.0
"""CallSiteValue binary dispatch — dig or EUF +, not factory_panic on add floor."""

from __future__ import annotations

from sugar_lift_py_tests.floor import CallSiteValue, SymbolicValue, TermValue
from sugar_lift_py_tests.ir import ctor, make_var
from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.lift_rpc import lift_file_payload
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.install_source_dig import method_body_is_attachable
from sugar_lift_py_tests.sugar.install_source_dig import (
    resolve_install_source_class_method,
)


def _csv(name: str = "g", *args) -> CallSiteValue:
    terms = [a.to_term(owner="t") for a in args]
    return CallSiteValue(
        target_name=name,
        arg_values=tuple(args),
        parameters=(),
        term=ctor(f"call:{name}", terms),
        body=None,
        site="t.py:1:0",
    )


def test_callsite_add_opaque_is_symbolic_plus() -> None:
    left = _csv("want_bytes", SymbolicValue(make_var("v")))
    right = _csv("sep", SymbolicValue(make_var("self")))
    outcome = left.add(right, site="t.py:1:0")
    assert isinstance(outcome, Complete)
    val = outcome.value
    assert isinstance(val, SymbolicValue)
    blob = repr(val.term)
    assert "+" in blob or "py." in blob
    assert "want_bytes" in blob or "call:want_bytes" in blob


def test_callsite_add_term_right() -> None:
    left = _csv("g", TermValue(1))
    outcome = left.add(TermValue(2), site="t.py:1:0")
    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, SymbolicValue)


def test_symbolic_add_euf() -> None:
    a = SymbolicValue(make_var("a"))
    outcome = a.add(TermValue(1), site="t.py:1:0")
    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, SymbolicValue)


def test_function_body_with_call_plus_lifts() -> None:
    """Dig g(x)+1 must not refuse solely for CallSiteValue.add gap."""
    src = (
        "def g(x):\n"
        "    return x\n"
        "def f(x):\n"
        "    return g(x) + 1\n"
        "def test_f():\n"
        "    assert f(2) == 3\n"
    )
    rpc = lift_file_payload(src, "t.py").to_rpc()
    reasons = " ".join(
        str(r.get("reason") or "")
        for r in ((rpc.get("factoryAuditSummary") or {}).get("unresolvedSites") or [])
    )
    assert "stand on the addition floor" not in reasons, reasons
    assert "CallSiteValue.add" not in reasons, reasons
    ax = account_lift_coverage(census_source(src, file="t.py"), rpc).to_json()[
        "assertions"
    ]
    assert ax["silently_unaccounted"] == 0
    # May lift (EUF/companion) or refuse for other floors — never silent.
    assert ax["lifted_cited"] + ax["refused_loud"] == 1


def test_signer_sign_attachable_after_binop_gate() -> None:
    fn = resolve_install_source_class_method("itsdangerous.Signer", "sign")
    assert fn is not None
    assert method_body_is_attachable(fn) is True


def test_signer_sign_unsign_no_add_floor_gap() -> None:
    src = (
        "from itsdangerous import Signer\n"
        "def test_s():\n"
        "    s = Signer('secret-key')\n"
        "    assert s.unsign(s.sign('value')) == b'value'\n"
    )
    rpc = lift_file_payload(src, "t.py").to_rpc()
    reasons = " ".join(
        str(r.get("reason") or "")
        for r in ((rpc.get("factoryAuditSummary") or {}).get("unresolvedSites") or [])
    )
    assert "stand on the addition floor" not in reasons, reasons
    ax = account_lift_coverage(census_source(src, file="t.py"), rpc).to_json()[
        "assertions"
    ]
    assert ax["silently_unaccounted"] == 0
    # Prefer lifted; refuse-loud ok for other unfinished floors.
    assert ax["lifted_cited"] + ax["refused_loud"] == 1
