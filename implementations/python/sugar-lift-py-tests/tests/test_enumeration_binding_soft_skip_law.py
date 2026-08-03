"""Instrument: soft FunctionBindingMiss / spelling by_name after resolve.

R axis: R_enumeration_binding_soft_skips

Permanent floor until dig cannot soft-skip authenticated binding refuse and
cannot serve abstract contracts by callee spelling after resolve.

Lying twins plant the illegal shapes; truthful twins require the production
membrane to stay clean and the dig to emit a named gap (not a wrong contract).
"""

from __future__ import annotations

import importlib.util
import textwrap
from pathlib import Path

import pytest

from sugar_lift_py_tests import lift_rpc

_KIT = Path(__file__).resolve().parents[1]
_SCANNER_PATH = _KIT / "scripts" / "enumeration_binding_soft_skip_law.py"
_SPEC = importlib.util.spec_from_file_location(
    "enumeration_binding_soft_skip_law", _SCANNER_PATH
)
assert _SPEC is not None and _SPEC.loader is not None
_SCANNER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_SCANNER)


def _enumerate(level: str, workspace_root: Path, at=None, seek: bool = False):
    captured = []
    original_send = lift_rpc._send
    lift_rpc._send = captured.append
    try:
        lift_rpc._dispatch_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "sugar.enumerate",
                "params": {
                    "level": level,
                    "workspace_root": str(workspace_root),
                    "at": at,
                    "seek": seek,
                    "options": {},
                },
            },
        )
    finally:
        lift_rpc._send = original_send
    assert len(captured) == 1, captured
    response = captured[0]
    assert "error" not in response, response
    return response["result"]


def test_scanner_flags_soft_function_binding_miss_continue(tmp_path: Path) -> None:
    """Lying twin: except FunctionBindingMiss: continue is red."""
    bad = tmp_path / "lift_rpc.py"
    bad.write_text(
        textwrap.dedent("""
            def dig(call):
                try:
                    fn = resolve_function_for_call(call)
                except FunctionBindingMiss:
                    continue
            """),
        encoding="utf-8",
    )
    offenders = _SCANNER.scan_sources([bad], root=tmp_path)
    kinds = {o.kind for o in offenders}
    assert "function-binding-miss-soft-skip" in kinds, offenders


def test_scanner_flags_fn_none_soft_skip(tmp_path: Path) -> None:
    """Lying twin: except FunctionBindingMiss: fn = None reopens soft-None."""
    bad = tmp_path / "lift_rpc.py"
    bad.write_text(
        textwrap.dedent("""
            def dig(call):
                try:
                    fn = resolve_function_for_call(call)
                except FunctionBindingMiss:
                    fn = None
            """),
        encoding="utf-8",
    )
    offenders = _SCANNER.scan_sources([bad], root=tmp_path)
    assert any(
        o.kind == "function-binding-miss-soft-skip" for o in offenders
    ), offenders


def test_scanner_flags_spelling_by_name_with_resolve(tmp_path: Path) -> None:
    """Lying twin: by_name[t] on resolve path is the spelling second door."""
    bad = tmp_path / "lift_rpc.py"
    bad.write_text(
        textwrap.dedent("""
            def dig(calls, universes):
                by_name = {name: (m, d) for name, m, d in universes}
                for call in calls:
                    fn = resolve_function_for_call(call)
                    t = call.func.id
                    if t in by_name:
                        cued.append(by_name[t])
            """),
        encoding="utf-8",
    )
    offenders = _SCANNER.scan_sources([bad], root=tmp_path)
    assert any(o.kind == "spelling-by-name-after-resolve" for o in offenders), offenders


def test_scanner_allows_gap_append_then_continue(tmp_path: Path) -> None:
    """Truthful membrane: named gap then continue is not soft silence."""
    ok = tmp_path / "lift_rpc.py"
    ok.write_text(
        textwrap.dedent("""
            def dig(call, at, gaps):
                try:
                    fn = resolve_function_for_call(call)
                except FunctionBindingMiss as miss:
                    gaps.append({
                        "memento": at,
                        "reason": f"FunctionBindingMiss name={miss.name!r} reason={miss.reason}",
                    })
                    continue
            """),
        encoding="utf-8",
    )
    offenders = _SCANNER.scan_sources([ok], root=tmp_path)
    soft = [o for o in offenders if o.kind == "function-binding-miss-soft-skip"]
    assert soft == [], soft


def test_production_membrane_has_zero_soft_skips() -> None:
    """Live offender census: production lift_rpc / tree_enumerate stay at R=0."""
    paths = _SCANNER.production_scan_roots(_KIT)
    assert paths, "production roots must exist"
    offenders = _SCANNER.scan_sources(paths, root=_KIT)
    assert offenders == [], (
        "R_enumeration_binding_soft_skips>0 — soft binding skip or spelling "
        f"by_name still live:\n"
        + "\n".join(f"  {o.path}:{o.line} [{o.kind}] {o.note}" for o in offenders)
    )


def _call_site_memento(tmp_path: Path, test_function_name: str) -> dict:
    """Walk source_files → functions → call_sites to the assertion cue memento."""
    file_key = _enumerate("source_files", tmp_path)["nodes"][0]["memento"]
    functions = {
        n["memento"].get("function_name")
        or n["memento"].get("source_function_name"): n["memento"]
        for n in _enumerate("functions", tmp_path, at=file_key)["nodes"]
    }
    assert test_function_name in functions, sorted(functions)
    sites = _enumerate("call_sites", tmp_path, at=functions[test_function_name])[
        "nodes"
    ]
    assert sites, "expected a call-site / assertion memento"
    return sites[0]["memento"]


def test_universe_dig_binding_miss_emits_gap_not_spelling_contract(
    tmp_path: Path,
) -> None:
    """Behavioral twin: unknown callee dig is a named gap, not a wrong contract.

    Plant: module has def pack; call site names unknown_callee. Resolve must
    refuse. Dig must not invent a universe from spelling. Gap reason names
    FunctionBindingMiss.
    """
    (tmp_path / "mod.py").write_text(
        textwrap.dedent("""
            def pack(a, *rest):
                return (a, rest)

            def test_a():
                assert unknown_callee(1) == 1
            """),
        encoding="utf-8",
    )
    call_at = _call_site_memento(tmp_path, "test_a")
    result = _enumerate("universe", tmp_path, at=call_at, seek=True)
    # Must not serve pack (or any) contract under unknown_callee spelling.
    for node in result["nodes"]:
        name = (node.get("memento") or {}).get("source_function_name") or (
            node.get("memento") or {}
        ).get("function_name")
        assert (
            name != "pack"
        ), f"spelling fallback served pack after binding miss: {node}"
    gap_text = " ".join(str(g.get("reason", "")) for g in result["gaps"])
    assert "FunctionBindingMiss" in gap_text, (
        f"expected FunctionBindingMiss gap, got nodes={result['nodes']!r} "
        f"gaps={result['gaps']!r}"
    )
    assert result["nodes"] == [], result["nodes"]


def test_universe_dig_prefers_module_binding_not_method_spelling(
    tmp_path: Path,
) -> None:
    """Method and module share spelling ``pack``; dig must serve module def.

    Old first-match / by_name last-wins could serve the method. Resolve +
    identity abstract must serve module ``pack(a, *rest)``.
    """
    (tmp_path / "mod.py").write_text(
        textwrap.dedent("""
            class Holder:
                def pack(self, *items):
                    return items

            def pack(a, *rest):
                return (a, rest)

            def test_a():
                assert pack(1, 2) == (1, (2,))
            """),
        encoding="utf-8",
    )
    call_at = _call_site_memento(tmp_path, "test_a")
    result = _enumerate("universe", tmp_path, at=call_at, seek=True)
    assert result["nodes"], result
    miss_gaps = [
        g for g in result["gaps"] if "FunctionBindingMiss" in str(g.get("reason", ""))
    ]
    assert miss_gaps == [], result["gaps"]
    mementos = [n.get("memento") or {} for n in result["nodes"]]
    assert any(
        m.get("source_function_name") == "pack" or m.get("function_name") == "pack"
        for m in mementos
    ), mementos
    # Must not sole-serve the method (self, *items) under module call spelling.
    # Module pack's def memento is the module-level function name "pack".
    assert all(
        "Holder" not in str(m.get("function_name", ""))
        and "Holder" not in str(m.get("source_function_name", ""))
        for m in mementos
    ), mementos
