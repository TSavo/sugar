"""Open dig membrane for strip towers — ambient post stays strip totality.

Coordinate law:
- Ambient covering post for total rstrip/lstrip returns is ¬suffix-of / ¬prefix-of
  on the **outer** callee (solver-safe logo post).
- Defaulted formals (``want_bytes(s, encoding=..., errors=...)``) bridge with
  fewer call args than the full parameter list.
- Same-module siblings seed **body dig** resolvers (not the mint dig set).
"""

from __future__ import annotations

from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report
from sugar_lift_py_tests.factory.source_fragment import SourceFragment


def _function_contracts(report):
    return [
        row.to_rpc()
        for row in report.payload.ir
        if hasattr(row, "to_rpc") and row.to_rpc().get("kind") == "function-contract"
    ]


def test_pure_rstrip_ambient_is_no_suffix() -> None:
    src = (
        "def strip_eq(x):\n"
        '    return x.rstrip(b"=")\n'
        "\n"
        "def test_it():\n"
        '    assert strip_eq(b"ab=") == b"ab"\n'
    )
    report = build_literal_call_report(
        source=src, filename="t.py", memento_file="t.py"
    )
    assert report is not None
    outer = next(
        c
        for c in _function_contracts(report)
        if c.get("bridgeSourceSymbol") == "call:strip_eq"
    )
    post = outer["post"]
    assert post["kind"] == "not"
    assert post["operands"][0]["name"] == "suffix-of"


def test_defaulted_formals_arity() -> None:
    """want_bytes has 3 params with 2 defaults — arity is (1, 3)."""
    src = (
        "def want_bytes(s, encoding=\"utf-8\", errors=\"strict\"):\n"
        "    return s\n"
    )
    fn = next(
        f
        for f in SourceFragment.from_source(src, "t.py").walk()
        if f.observed == "FunctionDef"
    )
    assert fn.function_positional_arity() == (1, 3)


def test_itsdangerous_base64_encode_ambient_no_suffix() -> None:
    src = (
        "import itsdangerous.encoding as enc\n"
        "\n"
        "def test_no_pad():\n"
        '    assert enc.base64_encode(b"provekit") == b"cHJvdmVraXQ"\n'
    )
    report = build_literal_call_report(
        source=src,
        filename="test_token_padding.py",
        memento_file="test_token_padding.py",
    )
    assert report is not None
    outer = next(
        c
        for c in _function_contracts(report)
        if c.get("bridgeSourceSymbol")
        == "call:itsdangerous.encoding.base64_encode"
    )
    post = outer["post"]
    assert post["kind"] == "not"
    assert post["operands"][0]["name"] == "suffix-of"
    audits = [
        a
        for a in report.payload.source_audits
        if isinstance(a, dict) and a.get("universe_kind") == "no-suffix-chars"
    ]
    assert audits


def test_itsdangerous_int_to_bytes_no_prefix() -> None:
    src = (
        "import itsdangerous.encoding as enc\n"
        "\n"
        "def test_int():\n"
        '    assert enc.int_to_bytes(1) == b"\\x01"\n'
    )
    report = build_literal_call_report(
        source=src, filename="t.py", memento_file="t.py"
    )
    assert report is not None
    outer = next(
        c
        for c in _function_contracts(report)
        if c.get("bridgeSourceSymbol") == "call:itsdangerous.encoding.int_to_bytes"
    )
    assert "prefix-of" in str(outer["post"])
