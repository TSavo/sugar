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
from sugar_lift_py_tests.factory import factory_panic_gap

FIXTURE_SOURCE = """\
def add(a, b):
    return a + b


def test_add():
    assert add(2, 3) == 5
"""


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    (tmp_path / "mathy.py").write_text(FIXTURE_SOURCE, encoding="utf-8")
    return tmp_path


def _enumerate(
    level: str, workspace_root: Path, at=None, seek: bool = False, options=None
):
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
                "options": options or {},
            },
        )
    finally:
        lift_rpc._send = original_send
    assert len(captured) == 1, captured
    response = captured[0]
    assert "error" not in response, response
    return response["result"]


def test_recovered_audit_tree_fold_matches_monolithic_bytes(project) -> None:
    expected = lift_rpc.audit_lift_file(
        FIXTURE_SOURCE, "mathy.py", recover_panics=True
    ).to_rpc()
    file_key = _enumerate("source_files", project)["nodes"][0]["memento"]
    definitions = _enumerate(
        "functions", project, at=file_key, options={"auditFrontier": True}
    )["nodes"]
    panics, effects, suppressed = [], [], []
    for definition in definitions:
        leaf = _enumerate(
            "facts",
            project,
            at=definition["memento"],
            seek=True,
            options={"auditFrontier": True},
        )["nodes"][0]["audit"]
        panics.extend(leaf["panics"])
        effects.extend(leaf["effects"])
        suppressed.extend(leaf["suppressedDescendants"])
    actual = {
        "kind": "recovered-construction-audit",
        "recoveryOverride": True,
        "status": "failed" if panics else "clean",
        "panics": panics,
        "effects": effects,
        "suppressedDescendants": suppressed,
    }
    assert json.dumps(actual, separators=(",", ":")) == json.dumps(
        expected, separators=(",", ":")
    )


def test_file_seed_panic_attaches_once_to_owning_node(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = """\
from fixture_module import VALUE

def first():
    return VALUE

def second():
    return VALUE

def third():
    return VALUE
"""
    (tmp_path / "seeded.py").write_text(source, encoding="utf-8")

    def panic_resolver(import_target, ctx):
        del import_target, ctx
        factory_panic_gap(
            owner="enumeration-seed-fixture",
            blame="seeded.py:1:0",
            observed="VALUE",
            requested="resolved import value",
            fix="attach the file seed panic to its owning node exactly once",
        )

    monkeypatch.setattr(
        "sugar_lift_py_tests.sugar.install_source_dig.resolve_install_source_value",
        panic_resolver,
    )
    lift_rpc._AUDIT_FILE_CONTEXTS.clear()
    file_key = _enumerate("source_files", tmp_path)["nodes"][0]["memento"]
    definitions = _enumerate(
        "functions", tmp_path, at=file_key, options={"auditFrontier": True}
    )["nodes"]
    assert len(definitions) == 4, "one module owner plus three definitions"

    panics = []
    for definition in definitions:
        # Rust SourceMemento::to_json preserves the qualified source spelling
        # but deliberately does not emit the Python-only `function_name` alias.
        at = dict(definition["memento"])
        at.pop("function_name", None)
        leaf = _enumerate(
            "facts",
            tmp_path,
            at=at,
            seek=True,
            options={"auditFrontier": True},
        )["nodes"][0]["audit"]
        panics.extend(leaf["panics"])

    owned = [
        panic
        for panic in panics
        if panic["gap"]["owner"] == "enumeration-seed-fixture"
    ]
    assert len(owned) == 1, owned


def test_audit_context_is_parsed_once_per_file_cid_and_mutation_misses(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sugar_lift_py_tests.factory.source_fragment import SourceFragment

    sibling = project / "sibling.py"
    sibling.write_text("def test_sibling():\n    assert 1 == 1\n", encoding="utf-8")
    lift_rpc._AUDIT_FILE_CONTEXTS.clear()
    original = SourceFragment.from_source.__func__
    parsed: list[str] = []

    def counted(cls, source: str, filename: str):
        parsed.append(filename)
        return original(cls, source, filename)

    monkeypatch.setattr(SourceFragment, "from_source", classmethod(counted))

    file_nodes = {
        node["memento"]["file"]: node["memento"]
        for node in _enumerate("source_files", project)["nodes"]
    }
    mathy_key = file_nodes["mathy.py"]
    sibling_key = file_nodes["sibling.py"]
    assert mathy_key["source_cid"]
    assert sibling_key["source_cid"]

    definitions = _enumerate(
        "functions", project, at=mathy_key, options={"auditFrontier": True}
    )["nodes"]
    for definition in definitions:
        _enumerate(
            "facts",
            project,
            at=definition["memento"],
            seek=True,
            options={"auditFrontier": True},
        )
    assert parsed.count("mathy.py") == 1

    _enumerate("functions", project, at=sibling_key, options={"auditFrontier": True})
    assert parsed.count("sibling.py") == 1

    (project / "mathy.py").write_text(
        FIXTURE_SOURCE + "\ndef test_changed():\n    assert 2 == 2\n", encoding="utf-8"
    )
    changed_nodes = {
        node["memento"]["file"]: node["memento"]
        for node in _enumerate("source_files", project)["nodes"]
    }
    assert changed_nodes["mathy.py"]["source_cid"] != mathy_key["source_cid"]
    _enumerate(
        "functions",
        project,
        at=changed_nodes["mathy.py"],
        options={"auditFrontier": True},
    )
    _enumerate("functions", project, at=sibling_key, options={"auditFrontier": True})

    assert parsed.count("mathy.py") == 2, "new file CID must parse once"
    assert parsed.count("sibling.py") == 1, "untouched sibling CID must stay warm"


def test_partial_audit_demand_does_not_compute_sibling_definitions(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lift_rpc._AUDIT_FILE_CONTEXTS.clear()
    demanded: list[str] = []
    original = lift_rpc.audit_lift_file

    def recording_audit(*args, **kwargs):
        target = kwargs.get("target_memento") or {}
        demanded.append(
            target.get("function_name")
            or target.get("source_function_name")
            or "<unknown>"
        )
        return original(*args, **kwargs)

    monkeypatch.setattr(lift_rpc, "audit_lift_file", recording_audit)
    file_key = _enumerate("source_files", project)["nodes"][0]["memento"]
    definitions = _enumerate(
        "functions", project, at=file_key, options={"auditFrontier": True}
    )["nodes"]
    target = next(
        node["memento"]
        for node in definitions
        if node["memento"].get("function_name") == "test_add"
    )

    _enumerate(
        "facts",
        project,
        at=target,
        seek=True,
        options={"auditFrontier": True},
    )

    assert demanded == ["test_add"]


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
    assert names == ["mathy.add", "test_add"]


def test_call_sites_scoped_to_enclosing_function(project: Path) -> None:
    file_memento = _enumerate("source_files", project)["nodes"][0]["memento"]
    functions = {
        n["memento"].get("function_name")
        or n["memento"].get("source_function_name"): n["memento"]
        for n in _enumerate("functions", project, at=file_memento)["nodes"]
    }
    add_call_sites = _enumerate("call_sites", project, at=functions["mathy.add"])[
        "nodes"
    ]
    assert add_call_sites == []

    test_add_call_sites = _enumerate("call_sites", project, at=functions["test_add"])[
        "nodes"
    ]
    assert len(test_add_call_sites) == 1


def test_assertions_and_facts_carry_the_fol(project: Path) -> None:
    file_memento = _enumerate("source_files", project)["nodes"][0]["memento"]
    functions = {
        n["memento"].get("function_name")
        or n["memento"].get("source_function_name"): n["memento"]
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
    # The call return has no sort warrant at atom construction, so Python
    # equality remains stated; enumeration must not resurrect bare `=`.
    assert formula["name"] == "py.eq"
    # `add(2, 3) == 5`: an EUF call-ctor compared to the literal 5.
    call_ctor = formula["args"][0]
    assert call_ctor["kind"] == "ctor"
    assert call_ctor["name"] == "call:add"
    literal = formula["args"][1]
    assert literal == {
        "kind": "const",
        "value": 5,
        "sort": {"kind": "primitive", "name": "Int"},
    }


def test_facts_seek_is_idempotent(project: Path) -> None:
    """Scan/seek coherence at the facts level (this landing's leaf, always
    seek-answered): re-asking for the SAME assertion memento must return the
    byte-identical node."""
    file_memento = _enumerate("source_files", project)["nodes"][0]["memento"]
    functions = {
        n["memento"].get("function_name")
        or n["memento"].get("source_function_name"): n["memento"]
        for n in _enumerate("functions", project, at=file_memento)["nodes"]
    }
    call_site_memento = _enumerate("call_sites", project, at=functions["test_add"])[
        "nodes"
    ][0]["memento"]
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
    response = _enumerate_raw(
        "call_sites", project, at={"file": "../outside_secret.py"}
    )
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
    assert names == ["mathy.add"]
    assert result["gaps"] == []


def test_callable_universe_identity_uses_content_and_qualified_spelling(
    tmp_path: Path,
) -> None:
    source = "def add(a, b):\n    return a + b\n"
    (tmp_path / "module_a.py").write_text(source, encoding="utf-8")
    (tmp_path / "module_b.py").write_text(source, encoding="utf-8")
    files = {
        node["memento"]["file"]: node["memento"]
        for node in _enumerate("source_files", tmp_path)["nodes"]
    }

    def identity(file_name: str):
        nodes = _enumerate("universe", tmp_path, at=files[file_name])["nodes"]
        assert len(nodes) == 1, nodes
        memento = nodes[0]["memento"]
        return (
            memento["source_cid"],
            memento.get("function_name")
            or memento.get("source_function_name")
            or memento.get("sourceFunctionName"),
        )

    module_a_once = identity("module_a.py")
    module_b_once = identity("module_b.py")
    module_a_twice = identity("module_a.py")

    assert module_a_once != module_b_once
    assert module_a_once == module_a_twice
    assert module_a_once[1] == "module_a.add"
    assert module_b_once[1] == "module_b.add"


def test_universe_seek_from_callsite_joins_by_bridge(project: Path) -> None:
    """CallSite-style seek: call:add → qualified mathy.add universe."""
    file_memento = _enumerate("source_files", project)["nodes"][0]["memento"]
    functions = {
        n["memento"].get("function_name")
        or n["memento"].get("source_function_name"): n["memento"]
        for n in _enumerate("functions", project, at=file_memento)["nodes"]
    }
    call_site_memento = _enumerate("call_sites", project, at=functions["test_add"])[
        "nodes"
    ][0]["memento"]
    result = _enumerate("universe", project, at=call_site_memento, seek=True)
    assert len(result["nodes"]) == 1
    node = result["nodes"][0]
    name = (node["audit"] or {}).get("name") or node["memento"].get("function_name")
    assert name == "mathy.add"
    assert node["memento"].get("function_name") == name
    assert result["gaps"] == []


def test_universe_seek_refuses_ambiguous_leaf_bridge(tmp_path: Path) -> None:
    source = """\
class A:
    def add(self, value):
        return value + 1

class B:
    def add(self, value):
        return value + 2

def test_add():
    assert add(1) == 2
"""
    (tmp_path / "ambiguous.py").write_text(source, encoding="utf-8")
    file_memento = _enumerate("source_files", tmp_path)["nodes"][0]["memento"]
    functions = {
        n["memento"].get("function_name")
        or n["memento"].get("source_function_name"): n["memento"]
        for n in _enumerate("functions", tmp_path, at=file_memento)["nodes"]
    }
    call_site_memento = _enumerate(
        "call_sites", tmp_path, at=functions["test_add"]
    )["nodes"][0]["memento"]

    result = _enumerate("universe", tmp_path, at=call_site_memento, seek=True)

    assert result["nodes"] == []
    assert len(result["gaps"]) == 1
    reason = result["gaps"][0]["reason"]
    assert "ambiguous universe sugar for callee call:add" in reason
    assert "ambiguous.A.add" in reason
    assert "ambiguous.B.add" in reason
