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
from sugar_lift_py_tests.canonicalizer import blake3_512_of, encode_jcs
from sugar_lift_py_tests.factory import factory_panic_gap
from sugar_lift_py_tests.ir import _json_like_to_value

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
        panic for panic in panics if panic["gap"]["owner"] == "enumeration-seed-fixture"
    ]
    assert len(owned) == 1, owned


def test_empty_package_module_enumerates_and_folds_as_an_empty_child_set(
    tmp_path: Path,
) -> None:
    package = tmp_path / "empty_package"
    package.mkdir()
    (package / "__init__.py").write_bytes(b"")

    file_nodes = _enumerate("source_files", tmp_path)["nodes"]
    file_key = next(
        node["memento"]
        for node in file_nodes
        if node["memento"]["file"] == "empty_package/__init__.py"
    )
    functions = _enumerate(
        "functions", tmp_path, at=file_key, options={"auditFrontier": True}
    )

    assert functions == {"nodes": [], "gaps": []}

    # The recovered consumer fold over a leaf file has no definition leaves to
    # request. Its identity is the same clean, empty audit the monolithic door
    # returns for the real zero-byte source.
    actual = {
        "kind": "recovered-construction-audit",
        "recoveryOverride": True,
        "status": "clean",
        "panics": [],
        "effects": [],
        "suppressedDescendants": [],
    }
    expected = lift_rpc.audit_lift_file(
        "", "empty_package/__init__.py", recover_panics=True
    ).to_rpc()
    assert actual == expected


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


def test_enumeration_file_context_cache_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUGAR_ENUMERATION_FILE_CACHE_LIMIT", "2")
    cache = lift_rpc.collections.OrderedDict()

    lift_rpc._remember_file_context(cache, "first", object())
    lift_rpc._remember_file_context(cache, "second", object())
    lift_rpc._remember_file_context(cache, "third", object())

    assert list(cache) == ["second", "third"]


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

    assertion_result = _enumerate(
        "assertions", project, at=call_site_memento, seek=True
    )
    assertions = assertion_result["nodes"]
    assert len(assertions) == 1
    assert assertion_result["termTable"]
    assertion_memento = assertions[0]["memento"]

    fact_result = _enumerate("facts", project, at=assertion_memento, seek=True)
    facts = fact_result["nodes"]
    assert len(facts) == 1
    term_table = fact_result["termTable"]
    assert term_table
    formula = facts[0]["payload"]
    assert formula["kind"] == "atomic"
    # The call return has no sort warrant at atom construction, so Python
    # equality remains stated; enumeration must not resurrect bare `=`.
    assert formula["name"] == "py.eq"
    # `add(2, 3) == 5`: both positions are closed references into the result table.
    call_ref, literal_ref = formula["args"]
    assert call_ref["kind"] == "term-ref"
    assert literal_ref["kind"] == "term-ref"
    assert call_ref["cid"] in term_table
    assert literal_ref["cid"] in term_table

    call_ctor = term_table[call_ref["cid"]]
    assert call_ctor["kind"] == "ctor"
    assert call_ctor["name"] == "call:add"
    assert all(arg["kind"] == "term-ref" for arg in call_ctor["args"])
    literal = term_table[literal_ref["cid"]]
    assert literal == {
        "kind": "const",
        "value": 5,
        "sort": {"kind": "primitive", "name": "Int"},
    }

    def resolve(cid: str, active: frozenset[str] = frozenset()):
        assert cid not in active
        node = term_table[cid]
        if node["kind"] != "ctor":
            return node
        return {
            "kind": "ctor",
            "name": node["name"],
            "args": [resolve(arg["cid"], active | {cid}) for arg in node["args"]],
        }

    for cid in term_table:
        canonical = encode_jcs(_json_like_to_value(resolve(cid))).encode()
        assert cid == blake3_512_of(canonical)


def test_every_formula_bearing_enumerate_level_is_closed(project: Path) -> None:
    def refs(value):
        found = set()
        if isinstance(value, dict):
            if value.get("kind") == "term-ref":
                found.add(value["cid"])
            else:
                for child in value.values():
                    found.update(refs(child))
        elif isinstance(value, list):
            for child in value:
                found.update(refs(child))
        return found

    def assert_closed(result):
        roots = refs({"nodes": result["nodes"], "gaps": result["gaps"]})
        if not roots:
            assert "termTable" not in result
            return
        table = result["termTable"]
        reachable = set()
        frontier = list(roots)
        while frontier:
            cid = frontier.pop()
            if cid in reachable:
                continue
            assert cid in table
            reachable.add(cid)
            frontier.extend(refs(table[cid]))
        assert set(table) == reachable

    file_result = _enumerate("source_files", project)
    assert_closed(file_result)
    file_memento = file_result["nodes"][0]["memento"]
    function_result = _enumerate("functions", project, at=file_memento)
    assert_closed(function_result)
    function_memento = next(
        node["memento"]
        for node in function_result["nodes"]
        if (node["memento"].get("function_name") or "").endswith("test_add")
    )
    callsite_result = _enumerate("call_sites", project, at=function_memento)
    assert_closed(callsite_result)
    callsite_memento = callsite_result["nodes"][0]["memento"]
    for level in ("assertions", "implications", "universe"):
        assert_closed(_enumerate(level, project, at=callsite_memento, seek=True))
    assertion = _enumerate("assertions", project, at=callsite_memento, seek=True)[
        "nodes"
    ][0]["memento"]
    assert_closed(_enumerate("facts", project, at=assertion, seek=True))


def test_closed_enumerate_result_rejects_omitted_term_table() -> None:
    nodes = [
        {
            "memento": {"file": "demo.py"},
            "audit": None,
            "payload": {"kind": "term-ref", "cid": "blake3-512:missing"},
        }
    ]

    with pytest.raises(ValueError, match="missing required `termTable`"):
        lift_rpc._closed_enumerate_result(nodes, [])


def test_closed_enumerate_result_rejects_dangling_term_ref() -> None:
    nodes = [
        {
            "memento": {"file": "demo.py"},
            "audit": None,
            "payload": {"kind": "term-ref", "cid": "blake3-512:missing"},
        }
    ]

    with pytest.raises(ValueError, match="missing term-table CID"):
        lift_rpc._closed_enumerate_result(nodes, [], term_tables=[{}])


def test_closed_enumerate_result_rejects_cycle_and_cid_mismatch() -> None:
    cycle = {
        "blake3-512:a": {
            "kind": "ctor",
            "name": "a",
            "args": [{"kind": "term-ref", "cid": "blake3-512:b"}],
        },
        "blake3-512:b": {
            "kind": "ctor",
            "name": "b",
            "args": [{"kind": "term-ref", "cid": "blake3-512:a"}],
        },
    }
    nodes = [
        {
            "memento": {"file": "demo.py"},
            "audit": None,
            "payload": {"kind": "term-ref", "cid": "blake3-512:a"},
        }
    ]
    with pytest.raises(ValueError, match="cyclic term-table reference"):
        lift_rpc._closed_enumerate_result(nodes, [], term_tables=[cycle])

    mismatch = {
        "blake3-512:not-the-content": {"kind": "var", "name": "x"},
    }
    nodes[0]["payload"]["cid"] = "blake3-512:not-the-content"
    with pytest.raises(ValueError, match="term-table CID mismatch"):
        lift_rpc._closed_enumerate_result(nodes, [], term_tables=[mismatch])


def test_closed_enumerate_result_rejects_malformed_child_and_conflict() -> None:
    malformed = {
        "blake3-512:parent": {
            "kind": "ctor",
            "name": "call:bad",
            "args": [{"kind": "var", "name": "inline-is-forbidden"}],
        }
    }
    nodes = [
        {
            "memento": {"file": "demo.py"},
            "audit": None,
            "payload": {"kind": "term-ref", "cid": "blake3-512:parent"},
        }
    ]
    with pytest.raises(ValueError, match="invalid child: expected kind `term-ref`"):
        lift_rpc._closed_enumerate_result(nodes, [], term_tables=[malformed])

    left = {"blake3-512:shared": {"kind": "var", "name": "left"}}
    right = {"blake3-512:shared": {"kind": "var", "name": "right"}}
    nodes[0]["payload"]["cid"] = "blake3-512:shared"
    with pytest.raises(ValueError, match="conflicting producer rows"):
        lift_rpc._closed_enumerate_result(nodes, [], term_tables=[left, right])


def test_closed_enumerate_result_prunes_unreachable_rows_and_omits_empty_table() -> (
    None
):
    leaf = {"kind": "var", "name": "reachable"}
    leaf_cid = blake3_512_of(encode_jcs(_json_like_to_value(leaf)).encode())
    unreachable = {"kind": "var", "name": "unreachable"}
    unreachable_cid = blake3_512_of(
        encode_jcs(_json_like_to_value(unreachable)).encode()
    )
    nodes = [
        {
            "memento": {"file": "demo.py"},
            "audit": None,
            "payload": {"kind": "term-ref", "cid": leaf_cid},
        }
    ]

    result = lift_rpc._closed_enumerate_result(
        nodes,
        [],
        term_tables=[{leaf_cid: leaf, unreachable_cid: unreachable}],
    )
    assert result["termTable"] == {leaf_cid: leaf}

    no_refs = lift_rpc._closed_enumerate_result(
        [{"memento": {"file": "demo.py"}, "audit": None, "payload": None}],
        [],
        term_tables=[{leaf_cid: leaf}],
    )
    assert "termTable" not in no_refs


def test_closed_enumerate_result_deduplicates_shared_reachable_subterms() -> None:
    leaf = {"kind": "var", "name": "x"}
    leaf_cid = blake3_512_of(encode_jcs(_json_like_to_value(leaf)).encode())
    parent_resolved = {
        "kind": "ctor",
        "name": "call:pair",
        "args": [leaf, leaf],
    }
    parent_cid = blake3_512_of(
        encode_jcs(_json_like_to_value(parent_resolved)).encode()
    )
    term_table = {
        leaf_cid: leaf,
        parent_cid: {
            "kind": "ctor",
            "name": "call:pair",
            "args": [
                {"kind": "term-ref", "cid": leaf_cid},
                {"kind": "term-ref", "cid": leaf_cid},
            ],
        },
    }
    nodes = [
        {
            "memento": {"file": "demo.py"},
            "audit": None,
            "payload": {
                "kind": "atomic",
                "name": "same",
                "args": [
                    {"kind": "term-ref", "cid": parent_cid},
                    {"kind": "term-ref", "cid": parent_cid},
                ],
            },
        }
    ]

    result = lift_rpc._closed_enumerate_result(nodes, [], term_tables=[term_table])

    assert result["termTable"] == term_table
    assert len(result["termTable"]) == 2


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


def test_same_leaf_callsite_scan_is_broad_but_each_seek_is_exact(
    tmp_path: Path,
) -> None:
    source = """\
def add(value):
    return value + 1

def test_add():
    assert add(1) == 2
    assert add(2) == 3
"""
    (tmp_path / "repeated.py").write_text(source, encoding="utf-8")
    file_memento = _enumerate("source_files", tmp_path)["nodes"][0]["memento"]
    functions = {
        n["memento"].get("function_name")
        or n["memento"].get("source_function_name"): n["memento"]
        for n in _enumerate("functions", tmp_path, at=file_memento)["nodes"]
    }

    scanned = _enumerate("call_sites", tmp_path, at=functions["test_add"])["nodes"]
    assert len(scanned) == 2
    assert [node["audit"]["bridgeSourceSymbol"] for node in scanned] == [
        "call:add",
        "call:add",
    ]
    assert len({json.dumps(node["memento"], sort_keys=True) for node in scanned}) == 2
    assert len({node["memento"]["span"]["start_line"] for node in scanned}) == 2

    for observed in scanned:
        sought = _enumerate("call_sites", tmp_path, at=observed["memento"], seek=True)
        assert sought["gaps"] == []
        assert len(sought["nodes"]) == 1
        assert sought["nodes"][0]["memento"] == observed["memento"]

        universe = _enumerate("universe", tmp_path, at=observed["memento"], seek=True)
        assert universe["gaps"] == []
        assert len(universe["nodes"]) == 1
        assert universe["nodes"][0]["memento"]["function_name"] == "repeated.add"


def test_same_leaf_calls_in_qualified_nested_owners_keep_distinct_identity(
    tmp_path: Path,
) -> None:
    source = """\
def add(value):
    return value + 1

class A:
    def check(self):
        assert add(1) == 2

class B:
    def check(self):
        assert add(2) == 3
"""
    (tmp_path / "nested.py").write_text(source, encoding="utf-8")
    file_memento = _enumerate("source_files", tmp_path)["nodes"][0]["memento"]
    functions = {
        n["memento"].get("function_name")
        or n["memento"].get("source_function_name"): n["memento"]
        for n in _enumerate("functions", tmp_path, at=file_memento)["nodes"]
    }

    observed = []
    for owner in ("nested.A.check", "nested.B.check"):
        sites = _enumerate("call_sites", tmp_path, at=functions[owner])["nodes"]
        assert len(sites) == 1
        assert sites[0]["audit"]["bridgeSourceSymbol"] == "call:add"
        sought = _enumerate("call_sites", tmp_path, at=sites[0]["memento"], seek=True)
        assert len(sought["nodes"]) == 1
        assert sought["nodes"][0]["memento"] == sites[0]["memento"]
        observed.append(sites[0]["memento"])

    assert observed[0] != observed[1]
    assert observed[0]["source_function_name"] == "nested.A.check"
    assert observed[1]["source_function_name"] == "nested.B.check"
    assert observed[0]["span"] != observed[1]["span"]


def test_callsite_bridge_lookup_uses_exact_locus_not_first_caller_edge(
    tmp_path: Path,
) -> None:
    source = """\
def add(value):
    return value + 1

def other(value):
    return value + 2

def test_calls():
    assert add(1) == 2
    assert other(1) == 3
"""
    (tmp_path / "distinct.py").write_text(source, encoding="utf-8")
    file_memento = _enumerate("source_files", tmp_path)["nodes"][0]["memento"]
    functions = {
        n["memento"].get("function_name")
        or n["memento"].get("source_function_name"): n["memento"]
        for n in _enumerate("functions", tmp_path, at=file_memento)["nodes"]
    }

    sites = _enumerate("call_sites", tmp_path, at=functions["test_calls"])["nodes"]
    assert [node["audit"]["bridgeSourceSymbol"] for node in sites] == [
        "call:add",
        "call:other",
    ]
    sought = _enumerate("universe", tmp_path, at=sites[1]["memento"], seek=True)
    assert sought["gaps"] == []
    assert len(sought["nodes"]) == 1
    assert sought["nodes"][0]["memento"]["function_name"] == "distinct.other"


def test_exact_seek_for_unknown_callsite_is_a_loud_gap_not_substitution(
    project: Path,
) -> None:
    file_memento = _enumerate("source_files", project)["nodes"][0]["memento"]
    forged = dict(file_memento)
    forged["function_name"] = "test_add"
    forged["span"] = {
        "start_line": 999,
        "start_col": 0,
        "end_line": 999,
        "end_col": 1,
    }
    forged["source_cid"] = "blake3-512:not-an-observed-callsite"

    for level in ("call_sites", "implications", "universe"):
        result = _enumerate(level, project, at=forged, seek=True)

        assert result["nodes"] == []
        assert len(result["gaps"]) == 1
        assert "no call site for exact memento" in result["gaps"][0]["reason"]
        assert result["gaps"][0]["memento"] == forged


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
    assert node["audit"]["bridgeSourceSymbol"] == "add"
    assert result["gaps"] == []


def test_implication_seek_returns_one_linker_demand_for_resolved_call(
    project: Path,
) -> None:
    file_memento = _enumerate("source_files", project)["nodes"][0]["memento"]
    functions = {
        n["memento"].get("function_name")
        or n["memento"].get("source_function_name"): n["memento"]
        for n in _enumerate("functions", project, at=file_memento)["nodes"]
    }
    call_site = _enumerate("call_sites", project, at=functions["test_add"])["nodes"][0][
        "memento"
    ]

    result = _enumerate("implications", project, at=call_site, seek=True)

    assert result["gaps"] == []
    assert len(result["nodes"]) == 1
    node = result["nodes"][0]
    question = node["audit"]
    demand = node["payload"]
    assert question["kind"] == "implication-question"
    assert question["targetSymbol"] == "call:add"
    assert question["candidateCount"] == 1
    assert demand["sourceContract"]["name"] == "test_add::assertion"
    assert demand["callEdge"]["target_symbol"] == "call:add"
    assert [
        candidate["contract"]["name"] for candidate in demand["targetCandidates"]
    ] == ["mathy.add"]
    assert all("status" not in row for row in (question, demand))


def test_implication_seek_returns_zero_candidate_demand_instead_of_false_empty(
    tmp_path: Path,
) -> None:
    (tmp_path / "debt.py").write_text(
        "def test_debt(x):\n    assert missing(x) == 1\n", encoding="utf-8"
    )
    file_memento = _enumerate("source_files", tmp_path)["nodes"][0]["memento"]
    function = _enumerate("functions", tmp_path, at=file_memento)["nodes"][0]["memento"]
    call_site = _enumerate("call_sites", tmp_path, at=function)["nodes"][0]["memento"]

    result = _enumerate("implications", tmp_path, at=call_site, seek=True)

    assert result["gaps"] == []
    assert len(result["nodes"]) == 1
    node = result["nodes"][0]
    question = node["audit"]
    demand = node["payload"]
    assert question["kind"] == "implication-question"
    assert question["candidateCount"] == 0
    assert question["targetSymbol"] == "call:missing"
    assert demand["targetCandidates"] == []
    assert demand["callEdge"]["target_symbol"] == "call:missing"
    assert "status" not in question


def test_term_ref_bridge_recovery_is_shared_by_callsite_universe_and_implication(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The response-owned term table is the one bridge-recovery boundary.

    Remove callEdges so every level must follow the assertion's closed term-ref
    graph. No level may depend on an inline constructor or invent a first edge.
    """
    original = lift_rpc._lift_file_for_enumeration
    lift_rpc._ENUMERATION_FILE_CONTEXTS.clear()

    def without_call_edges(workspace_root, root, file_rel):
        items, _edges, term_table = original(workspace_root, root, file_rel)
        return items, [], term_table

    monkeypatch.setattr(lift_rpc, "_lift_file_for_enumeration", without_call_edges)
    file_memento = _enumerate("source_files", project)["nodes"][0]["memento"]
    functions = {
        n["memento"].get("function_name")
        or n["memento"].get("source_function_name"): n["memento"]
        for n in _enumerate("functions", project, at=file_memento)["nodes"]
    }
    callsite_result = _enumerate("call_sites", project, at=functions["test_add"])
    call_site = callsite_result["nodes"][0]

    assert call_site["audit"]["bridgeSourceSymbol"] == "call:add"
    assert callsite_result["termTable"]

    implication = _enumerate(
        "implications", project, at=call_site["memento"], seek=True
    )
    assert implication["gaps"] == []
    assert implication["nodes"][0]["audit"]["targetSymbol"] == "call:add"
    assert implication["nodes"][0]["audit"]["candidateCount"] == 1
    assert implication["termTable"]

    universe = _enumerate("universe", project, at=call_site["memento"], seek=True)
    assert universe["gaps"] == []
    assert len(universe["nodes"]) == 1
    assert universe["nodes"][0]["memento"]["function_name"] == "mathy.add"
    assert universe["termTable"]


def test_distinct_descendant_demands_reuse_file_cid_context(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lift_rpc._ENUMERATION_FILE_CONTEXTS.clear()
    original = lift_rpc.lift_file_payload
    crossings = 0

    def counted(source: str, filename: str):
        nonlocal crossings
        crossings += 1
        return original(source, filename)

    monkeypatch.setattr(lift_rpc, "lift_file_payload", counted)
    file_memento = _enumerate("source_files", project)["nodes"][0]["memento"]
    functions = _enumerate("functions", project, at=file_memento)["nodes"]
    _enumerate("call_sites", project, at=functions[-1]["memento"])
    assert crossings == 1

    (project / "mathy.py").write_text(
        FIXTURE_SOURCE + "\n# changed\n", encoding="utf-8"
    )
    changed_file = _enumerate("source_files", project)["nodes"][0]["memento"]
    _enumerate("functions", project, at=changed_file)
    assert crossings == 2


def test_datetime_message_101_cmp_shape_reuses_context_without_edge_substitution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real datetime crash arrived asking for date._cmp call sites.

    Pin the exact lines 1201-1205 shape and the process-lifetime pressure that
    preceded message 101. Every demand must answer from one file reduction.
    """
    (tmp_path / "datetime.py").write_text(
        """\
def _cmp(left, right):
    return 0

class date:
    def _cmp(self, other):
        assert isinstance(other, date)
        y, m, d = self._year, self._month, self._day
        y2, m2, d2 = other._year, other._month, other._day
        return _cmp((y, m, d), (y2, m2, d2))
""",
        encoding="utf-8",
    )
    lift_rpc._ENUMERATION_FILE_CONTEXTS.clear()
    original = lift_rpc.lift_file_payload
    crossings = 0

    def counted(source: str, filename: str):
        nonlocal crossings
        crossings += 1
        return original(source, filename)

    monkeypatch.setattr(lift_rpc, "lift_file_payload", counted)
    file_memento = _enumerate("source_files", tmp_path)["nodes"][0]["memento"]
    functions = {
        node["memento"].get("function_name")
        or node["memento"].get("source_function_name"): node["memento"]
        for node in _enumerate("functions", tmp_path, at=file_memento)["nodes"]
    }

    for _ in range(101):
        result = _enumerate("call_sites", tmp_path, at=functions["datetime.date._cmp"])
        assert result["gaps"] == []
        assert len(result["nodes"]) == 1
        assert "bridgeSourceSymbol" not in result["nodes"][0]["audit"]

    assert crossings == 1


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
    call_site_memento = _enumerate("call_sites", tmp_path, at=functions["test_add"])[
        "nodes"
    ][0]["memento"]

    result = _enumerate("universe", tmp_path, at=call_site_memento, seek=True)

    assert result["nodes"] == []
    assert len(result["gaps"]) == 1
    reason = result["gaps"][0]["reason"]
    assert "ambiguous universe sugar for callee call:add" in reason
    assert "ambiguous.A.add" in reason
    assert "ambiguous.B.add" in reason
