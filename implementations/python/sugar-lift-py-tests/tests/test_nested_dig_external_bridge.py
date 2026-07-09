"""Nested dig: ExternalBridge only when nested_external_bridge=True, so towers finish without top-level poison.

Law:
- Opt-in ``nested_external_bridge=True``: resolved callee whose body cannot open
  emits symbolic ``call:f(...)`` so outer towers finish under dig orientation.
- Default mint (flag False): nested gaps stay Incomplete — ambient closed strip
  stays logo-safe (no str.suffixof encoding STOP).
- Ambient for total strip returns remains closed strip (prefer early).
"""

from __future__ import annotations

import inspect

import itsdangerous.encoding as enc

from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.factory.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.literal_call_report import (
    _resolver_nodes,
    _with_module_sibling_functions,
    build_literal_call_report,
)
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.factory.sugar_constructors import build_control_flow_body_sugar


def test_open_dig_base64_encode_tower_when_nested_bodies_fail() -> None:
    """Direct dig finishes: out = rstrip(urlsafe(want_bytes(string)), b'=')"""
    path = inspect.getsourcefile(enc)
    assert path is not None
    text = open(path, encoding="utf-8").read()
    root = SourceFragment.from_source(text, path)
    locals_ = {
        f.function_name(): f for f in root.walk() if f.observed == "FunctionDef"
    }
    for frag in locals_.values():
        frag.node._sugar_source = text  # type: ignore[attr-defined]
        frag.node._sugar_file = path  # type: ignore[attr-defined]
    fns = {
        **locals_,
        **{f"itsdangerous.encoding.{k}": v for k, v in locals_.items()},
    }
    fns = _with_module_sibling_functions(fns, module_hint="itsdangerous.encoding")
    fns = _with_module_sibling_functions(fns, module_hint="base64")
    ctx = FactoryBuildContext(
        filename=path,
        catalog=default_catalog(),
        name_resolver=_resolver_nodes(fns, {}),
        import_aliases={"base64": "base64"},
        from_imports={},
        # Opt-in: nested ExternalBridge so outer tower finishes when nested
        # bodies cannot open (isinstance / module Names). Default mint path
        # leaves this False for logo-safe ambient strip.
        nested_external_bridge=True,
    )
    sugar = build_control_flow_body_sugar(locals_["base64_encode"], ctx)
    blob = str(sugar.constraint_formulas())
    assert "call:rstrip" in blob
    assert "call:base64.urlsafe_b64encode" in blob or "urlsafe_b64encode" in blob
    assert "call:want_bytes" in blob


def test_mint_ambient_still_closed_strip_no_suffix() -> None:
    """Mint ambient for base64_encode stays ¬suffix-of (logo post), not EUF tower."""
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
    contracts = [
        row.to_rpc()
        for row in report.payload.ir
        if hasattr(row, "to_rpc") and row.to_rpc().get("kind") == "function-contract"
    ]
    outer = next(
        c
        for c in contracts
        if c.get("bridgeSourceSymbol")
        == "call:itsdangerous.encoding.base64_encode"
    )
    post = outer["post"]
    assert post["kind"] == "not"
    assert post["operands"][0]["name"] == "suffix-of"
    # Must not ambient-export the open dig EUF tower.
    assert "call:rstrip" not in str(post)
