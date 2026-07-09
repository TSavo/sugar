# SPDX-License-Identifier: MIT OR Apache-2.0
"""Part 6, Phase 2: `sugar.enumerate` (`protocol/specs/2026-07-08-enumeration-protocol.md`).

Exercises `_handle_enumerate` directly (in-process, no subprocess spawn --
the rust side's spawn/wire round trip is covered by
`sugar-compiler/tests/enumerate_conformance.rs`, which drives this SAME
handler through the real JSON-RPC membrane end to end).
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from sugar_lift_py_tests import lift_rpc

FIXTURE_SOURCE = '''\
def add(a, b):
    return a + b


def test_add():
    assert add(2, 3) == 5
'''


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    (tmp_path / "mathy.py").write_text(FIXTURE_SOURCE, encoding="utf-8")
    return tmp_path


def _enumerate(level: str, workspace_root: Path, at=None, seek: bool = False):
    """Call `_handle_enumerate` directly and capture its `_send` output by
    monkeypatching the module's `_send` for the duration of one call."""
    captured = []
    original_send = lift_rpc._send
    lift_rpc._send = captured.append
    try:
        lift_rpc._handle_enumerate(
            1,
            {
                "level": level,
                "workspace_root": str(workspace_root),
                "at": at,
                "seek": seek,
            },
        )
    finally:
        lift_rpc._send = original_send
    assert len(captured) == 1, captured
    response = captured[0]
    assert "error" not in response, response
    return response["result"]


def test_source_files_scan_finds_the_fixture_file(project: Path) -> None:
    result = _enumerate("source_files", project)
    assert result["gaps"] == []
    files = [n["memento"]["file"] for n in result["nodes"]]
    assert files == ["mathy.py"]


def test_source_files_seek_matches_by_file(project: Path) -> None:
    scanned = _enumerate("source_files", project)["nodes"]
    memento = scanned[0]["memento"]
    seeked = _enumerate("source_files", project, at=memento, seek=True)["nodes"]
    assert len(seeked) == 1
    assert seeked[0]["memento"] == memento


def test_functions_finds_both_the_contract_owner_and_the_enclosing_test(
    project: Path,
) -> None:
    file_memento = _enumerate("source_files", project)["nodes"][0]["memento"]
    result = _enumerate("functions", project, at=file_memento)
    names = sorted(
        n["memento"].get("function_name") or n["memento"].get("source_function_name")
        for n in result["nodes"]
    )
    assert names == ["add", "test_add"]


def test_call_sites_scoped_to_enclosing_function(project: Path) -> None:
    file_memento = _enumerate("source_files", project)["nodes"][0]["memento"]
    functions = {
        n["memento"].get("function_name") or n["memento"].get("source_function_name"): n[
            "memento"
        ]
        for n in _enumerate("functions", project, at=file_memento)["nodes"]
    }
    add_call_sites = _enumerate("call_sites", project, at=functions["add"])["nodes"]
    assert add_call_sites == []

    test_add_call_sites = _enumerate("call_sites", project, at=functions["test_add"])[
        "nodes"
    ]
    assert len(test_add_call_sites) == 1


def test_assertions_and_facts_carry_the_fol(project: Path) -> None:
    file_memento = _enumerate("source_files", project)["nodes"][0]["memento"]
    functions = {
        n["memento"].get("function_name") or n["memento"].get("source_function_name"): n[
            "memento"
        ]
        for n in _enumerate("functions", project, at=file_memento)["nodes"]
    }
    call_sites = _enumerate("call_sites", project, at=functions["test_add"])["nodes"]
    assert len(call_sites) == 1
    call_site_memento = call_sites[0]["memento"]

    assertions = _enumerate("assertions", project, at=call_site_memento, seek=True)[
        "nodes"
    ]
    assert len(assertions) == 1
    assertion_memento = assertions[0]["memento"]

    facts = _enumerate("facts", project, at=assertion_memento, seek=True)["nodes"]
    assert len(facts) == 1
    formula = facts[0]["payload"]
    assert formula["kind"] == "atomic"
    assert formula["name"] == "="
    # `add(2, 3) == 5`: an EUF call-ctor equated to the literal 5.
    call_ctor = formula["args"][0]
    assert call_ctor["kind"] == "ctor"
    assert call_ctor["name"] == "call:add"
    literal = formula["args"][1]
    assert literal == {"kind": "const", "value": 5, "sort": {"kind": "primitive", "name": "Int"}}


def test_facts_seek_is_idempotent(project: Path) -> None:
    """Scan/seek coherence at the facts level (this landing's leaf, always
    seek-answered): re-asking for the SAME assertion memento must return the
    byte-identical node."""
    file_memento = _enumerate("source_files", project)["nodes"][0]["memento"]
    functions = {
        n["memento"].get("function_name") or n["memento"].get("source_function_name"): n[
            "memento"
        ]
        for n in _enumerate("functions", project, at=file_memento)["nodes"]
    }
    call_site_memento = _enumerate(
        "call_sites", project, at=functions["test_add"]
    )["nodes"][0]["memento"]
    assertion_memento = _enumerate(
        "assertions", project, at=call_site_memento, seek=True
    )["nodes"][0]["memento"]

    first = _enumerate("facts", project, at=assertion_memento, seek=True)["nodes"]
    second = _enumerate("facts", project, at=assertion_memento, seek=True)["nodes"]
    assert first == second


def test_unknown_level_is_a_typed_rpc_error(project: Path) -> None:
    captured = []
    original_send = lift_rpc._send
    lift_rpc._send = captured.append
    try:
        lift_rpc._handle_enumerate(
            1, {"level": "not-a-real-level", "workspace_root": str(project)}
        )
    finally:
        lift_rpc._send = original_send
    assert len(captured) == 1
    assert captured[0]["error"]["code"] == -32602


def test_facts_on_a_missing_memento_is_a_gap_not_a_crash(project: Path) -> None:
    fake_memento = {
        "kind": "source-memento",
        "file": "mathy.py",
        "function_name": "add",
        "span": {"start_line": 999, "start_col": 0, "end_line": 999, "end_col": 1},
        "param_names": [],
        "source_cid": "blake3-512:doesnotexist",
        "template_cid": "blake3-512:doesnotexist",
    }
    result = _enumerate("facts", project, at=fake_memento, seek=True)
    assert result["nodes"] == []
    assert len(result["gaps"]) == 1
    assert "reason" in result["gaps"][0]


def _enumerate_raw(level: str, workspace_root, at=None, seek: bool = False):
    """Like _enumerate but returns the raw response (for error/gap cases)."""
    captured = []
    original_send = lift_rpc._send
    lift_rpc._send = captured.append
    try:
        lift_rpc._handle_enumerate(
            1,
            {
                "level": level,
                "workspace_root": str(workspace_root),
                "at": at,
                "seek": seek,
            },
        )
    finally:
        lift_rpc._send = original_send
    assert len(captured) == 1, captured
    return captured[0]


def test_enumerate_refuses_path_traversal(project) -> None:
    """SECURITY (macroscope on #3862): a forged memento whose file escapes
    the workspace root is refused as a gap, never lifted."""
    outside = project.parent / "outside_secret.py"
    outside.write_text("def f():\n    assert 1 == 1\n", encoding="utf-8")
    response = _enumerate_raw("call_sites", project, at={"file": "../outside_secret.py"})
    assert "error" not in response, response
    result = response["result"]
    assert result["nodes"] == []
    assert len(result["gaps"]) == 1
    assert "escapes the workspace root" in result["gaps"][0]["reason"]


def test_enumerate_empty_file_is_an_empty_level_not_an_error(project) -> None:
    """A comments-only file has no source sites: empty level, not -32603."""
    (project / "empty_mod.py").write_text("# nothing here\n", encoding="utf-8")
    response = _enumerate_raw("assertions", project, at={"file": "empty_mod.py"})
    assert "error" not in response, response
    assert response["result"]["nodes"] == []


def test_universe_scan_lists_function_contract_rows(project: Path) -> None:
    """File-level universe scan surfaces batch function-contract names."""
    file_memento = _enumerate("source_files", project)["nodes"][0]["memento"]
    result = _enumerate("universe", project, at=file_memento, seek=False)
    names = sorted(
        (n["audit"] or {}).get("name")
        or n["memento"].get("name")
        or n["memento"].get("function_name")
        for n in result["nodes"]
    )
    assert any(n and "add" in n and "callable" in n for n in names), names
    assert result["gaps"] == []


def test_universe_seek_from_callsite_joins_by_bridge(project: Path) -> None:
    """CallSite-style seek: call:add → mathy::add::callable universe."""
    file_memento = _enumerate("source_files", project)["nodes"][0]["memento"]
    functions = {
        n["memento"].get("function_name") or n["memento"].get("source_function_name"): n[
            "memento"
        ]
        for n in _enumerate("functions", project, at=file_memento)["nodes"]
    }
    call_site_memento = _enumerate(
        "call_sites", project, at=functions["test_add"]
    )["nodes"][0]["memento"]
    result = _enumerate("universe", project, at=call_site_memento, seek=True)
    assert len(result["nodes"]) == 1
    node = result["nodes"][0]
    name = (node["audit"] or {}).get("name") or node["memento"].get("function_name")
    assert name and "callable" in name
    assert node["memento"].get("function_name") == name
    assert result["gaps"] == []
