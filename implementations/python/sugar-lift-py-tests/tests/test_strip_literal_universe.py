from __future__ import annotations

from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report

_STRIP_SOURCE = (
    "import itsdangerous.encoding as enc\n"
    "\n"
    "def test_no_pad():\n"
    '    assert enc.base64_encode(b"provekit") == b"cHJvdmVraXQ"\n'
)


def test_rstrip_body_mints_no_suffix_universe_on_outer_callee() -> None:
    """Closed strip universe attaches to outer base64_encode, not the stuck inner call."""
    report = build_literal_call_report(
        source=_STRIP_SOURCE,
        filename="test_token_padding.py",
        memento_file="test_token_padding.py",
    )
    assert report is not None
    contracts = [
        row.to_rpc()
        for row in report.payload.ir
        if hasattr(row, "to_rpc") and row.to_rpc().get("kind") == "function-contract"
    ]
    bridges = [c.get("bridgeSourceSymbol") for c in contracts]
    assert "call:itsdangerous.encoding.base64_encode" in bridges
    outer = next(
        c
        for c in contracts
        if c.get("bridgeSourceSymbol") == "call:itsdangerous.encoding.base64_encode"
    )
    post = outer["post"]
    assert post["kind"] == "not"
    atomic = post["operands"][0]
    assert atomic["kind"] == "atomic"
    assert atomic["name"] == "suffix-of"
    assert atomic["args"][0]["value"] == "="
    assert atomic["args"][1]["name"] == "out"

    roles = {
        m.role if hasattr(m, "role") else m.get("role")
        for m in report.payload.source_mementos
    }
    assert "python.translate-universe" in roles

    audits = [
        a
        for a in report.payload.source_audits
        if isinstance(a, dict) and a.get("universe_kind") == "no-suffix-chars"
    ]
    assert audits, "expected no-suffix-chars universe_kind on source audit"
