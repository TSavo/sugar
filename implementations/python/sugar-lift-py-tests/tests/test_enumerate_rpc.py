# SPDX-License-Identifier: MIT OR Apache-2.0
"""Part 6, Phase 2: `sugar.enumerate` (`protocol/specs/2026-07-08-enumeration-protocol.md`).

Exercises `_handle_enumerate` directly (in-process, no subprocess spawn --
the rust side's spawn/wire round trip is covered by
`sugar-compiler/tests/enumerate_conformance.rs`, which drives this SAME
handler through the real JSON-RPC membrane end to end).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sugar_lift_py_tests import lift_rpc
from sugar_lift_py_tests.canonicalizer import blake3_512_of, encode_jcs
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
    """Dispatch a real ``sugar.enumerate`` request and capture its response."""
    options = dict(options or {})
    if options.get("auditFrontier") is True:
        options.setdefault("allowedBrokenComponents", ["python"])
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
                    "options": options,
                },
            },
        )
    finally:
        lift_rpc._send = original_send
    assert len(captured) == 1, captured
    response = captured[0]
    assert "error" not in response, response
    return response["result"]


def test_enumeration_file_context_cache_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUGAR_ENUMERATION_FILE_CACHE_LIMIT", "2")
    cache = lift_rpc.collections.OrderedDict()

    lift_rpc._remember_file_context(cache, "first", object())
    lift_rpc._remember_file_context(cache, "second", object())
    lift_rpc._remember_file_context(cache, "third", object())

    assert list(cache) == ["second", "third"]


def test_source_files_scan_finds_the_fixture_file(project: Path) -> None:
    result = _enumerate("source_files", project)
    assert result["gaps"] == []
    files = [n["memento"]["file"] for n in result["nodes"]]
    assert files == ["mathy.py"]


def _audit_envelope(workspace: Path, file: str = "mathy.py") -> dict:
    file_key = next(
        node["memento"]
        for node in _enumerate("source_files", workspace)["nodes"]
        if node["memento"]["file"] == file
    )
    module = _enumerate(
        "functions", workspace, at=file_key, options={"auditFrontier": True}
    )["nodes"]
    assert len(module) == 1
    return _enumerate(
        "facts",
        workspace,
        at=module[0]["memento"],
        seek=True,
        options={"auditFrontier": True},
    )["nodes"][0]["audit"]


def _audit_leaf(workspace: Path, file: str = "mathy.py") -> dict:
    envelope = _audit_envelope(workspace, file)
    return {
        **envelope["semanticCore"],
        "sourceAudit": envelope["auxiliaryRows"]["sourceAudit"],
    }


def test_audit_leaf_separates_closed_semantic_core_from_typed_auxiliary_rows(
    project: Path,
) -> None:
    leaf = _audit_envelope(project)

    assert set(leaf) == {"semanticCore", "auxiliaryRows"}
    assert set(leaf["semanticCore"]) == {
        "kind",
        "recoveryOverride",
        "status",
        "panics",
        "effects",
        "suppressedDescendants",
    }
    assert set(leaf["auxiliaryRows"]) == {"sourceAudit"}
    assert leaf["auxiliaryRows"]["sourceAudit"]["role"] == "mathy.py"


def _script_roll_call(monkeypatch: pytest.MonkeyPatch, answer: str) -> None:
    """Fill the real reporter interface with a controlled roll-call answer."""
    from sugar_source_tree.panic import SugarNotWritten
    from sugar_source_tree.roll_call import MinorityReport
    import sugar_source_tree.roll_call as roll_call

    def scripted_discharge(source_file):
        list(source_file.nodes())
        reporter = source_file.reporter
        # Key the twin the way MinorityReport._by_coordinate keys the real
        # roll: the authenticated source coordinate alongside the CID. Equal
        # source text shares a CID at distinct loci -- a load-site Name can
        # carry its Param's CID -- and deduping on the CID alone silently
        # drops the second locus the reporter is obliged to keep.
        by_coordinate = {}
        for node in reporter.registered:
            entry = roll_call.roster_entry_for(node)
            key = (
                entry.file,
                entry.start_line,
                entry.start_col,
                entry.kind,
                entry.cid,
            )
            by_coordinate.setdefault(key, node)
        nodes = list(by_coordinate.values())
        assert nodes
        absent = nodes[-1]
        present = nodes if answer in {"truthful", "lying"} else nodes[:-1]
        for node in present:
            reporter.present_fact(node)
        if answer in {"lying", "minority"}:
            reporter.report_gap(
                absent,
                SugarNotWritten(
                    owner="rpc-roll-call-twin",
                    observed=absent.kind,
                    requested="written tree sugar",
                    fix="write the node sugar",
                ),
            )
        return MinorityReport(reporter)

    monkeypatch.setattr(roll_call, "discharge", scripted_discharge)


def test_rpc_roll_call_truthful_twin_projects_present_as_warranted(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _script_roll_call(monkeypatch, "truthful")
    leaf = _audit_leaf(project)
    assert leaf["status"] == "clean"
    assert leaf["panics"] == []
    assert leaf["sourceAudit"]["totals"]["source_unresolved"] == 0
    assert {row["status"] for row in leaf["sourceAudit"]["loci"]} == {"warranted"}


def test_rpc_roll_call_lying_twin_does_not_hide_gap_testimony(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _script_roll_call(monkeypatch, "lying")
    leaf = _audit_leaf(project)
    assert leaf["status"] == "failed"
    assert len(leaf["panics"]) == 1
    assert leaf["sourceAudit"]["totals"]["source_unresolved"] == 0


def test_rpc_roll_call_minority_twin_projects_one_absent_everywhere(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-home #6025's seed-panic law: one absent owns one panic row."""
    _script_roll_call(monkeypatch, "minority")
    leaf = _audit_leaf(project)
    unresolved = [
        row for row in leaf["sourceAudit"]["loci"] if row["status"] == "unresolved"
    ]
    assert leaf["status"] == "failed"
    assert len(leaf["panics"]) == 1
    assert len(unresolved) == 1
    assert leaf["sourceAudit"]["totals"]["source_unresolved"] == 1
    assert leaf["panics"][0]["gap"]["kind"] == "SugarNotWritten"
    assert leaf["panics"][0]["gap"]["nodeKind"] == unresolved[0]["kind"]


def test_rpc_roll_call_silently_unaccounted_twin_stays_loud(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _script_roll_call(monkeypatch, "silent")
    leaf = _audit_leaf(project)
    assert leaf["status"] == "failed"
    assert len(leaf["panics"]) == 1
    assert leaf["panics"][0]["gap"]["kind"] == "UnaccountedConstruction"
    assert leaf["sourceAudit"]["totals"]["source_unresolved"] == 1


def test_roll_call_audit_uses_one_construction_and_one_discharge(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-home monolithic-fold and partial-demand laws onto one module roll."""
    from sugar_source_tree.tree import SourceFile
    import sugar_source_tree.roll_call as roll_call

    calls = {"construction": 0, "discharge": 0}
    original_from_path = SourceFile.from_path.__func__
    original_discharge = roll_call.discharge

    def counted_from_path(cls, *args, **kwargs):
        calls["construction"] += 1
        return original_from_path(cls, *args, **kwargs)

    def counted_discharge(source_file):
        calls["discharge"] += 1
        return original_discharge(source_file)

    monkeypatch.setattr(SourceFile, "from_path", classmethod(counted_from_path))
    monkeypatch.setattr(roll_call, "discharge", counted_discharge)
    leaf = _audit_leaf(project)

    assert leaf["sourceAudit"]["totals"]["source_loci"] > 0
    assert calls == {"construction": 1, "discharge": 1}


def test_roll_call_law_same_bytes_at_distinct_seats_keep_distinct_loci(
    tmp_path: Path,
) -> None:
    """Re-homed: source identity may match, but each RPC seat stays distinct."""
    source = "def f():\n    return 1\n"
    (tmp_path / "first.py").write_text(source, encoding="utf-8")
    (tmp_path / "second.py").write_text(source, encoding="utf-8")

    first = _audit_leaf(tmp_path, "first.py")["sourceAudit"]
    second = _audit_leaf(tmp_path, "second.py")["sourceAudit"]
    assert first["role"] == "first.py"
    assert second["role"] == "second.py"
    assert {row["source_cid"] for row in first["loci"]} == {
        row["source_cid"] for row in second["loci"]
    }
    assert {row["locus"]["file"] for row in first["loci"]} == {"first.py"}
    assert {row["locus"]["file"] for row in second["loci"]} == {"second.py"}


def test_roll_call_law_empty_file_has_one_canonical_module_leaf(tmp_path: Path) -> None:
    """Re-homed: the empty child-set fold is one module roll-call projection."""
    (tmp_path / "empty.py").write_bytes(b"")
    leaf = _audit_leaf(tmp_path, "empty.py")
    assert leaf["sourceAudit"]["role"] == "empty.py"
    assert leaf["sourceAudit"]["totals"]["source_loci"] >= 1


@pytest.mark.parametrize(
    "panic_type",
    [
        pytest.param("VocabularyMissing", id="missing-tree-vocabulary"),
        pytest.param("BackendDefect", id="invalid-backend-shape"),
        pytest.param("SugarNotWritten", id="known-construction-missing"),
        pytest.param(
            "RuntimeSelectedContextManager", id="runtime-selected-construction"
        ),
    ],
)
def test_rpc_entry_preserves_tree_panic_role(
    panic_type: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-home the no-recovery law; preserve each panic at the RPC entry."""
    import sugar_source_tree.panic as tree_panic

    panic = getattr(tree_panic, panic_type)(
        owner="rpc-role-map",
        observed="fixture",
        requested="role-correct answer",
        fix="preserve the concrete tree taxonomy",
    )
    (tmp_path / "role.py").write_text("x = 1\n", encoding="utf-8")
    request = {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "sugar.enumerate",
        "params": {
            "level": "facts",
            "workspace_root": str(tmp_path),
            "at": {"file": "role.py"},
            "seek": True,
            "options": {"auditFrontier": True},
        },
    }
    requests = iter([request])
    sent = []
    monkeypatch.setattr(lift_rpc, "_recv", lambda: next(requests, None))
    monkeypatch.setattr(
        "sugar_source_tree.tree.SourceFile.from_path",
        classmethod(lambda _cls, *_args, **_kwargs: (_ for _ in ()).throw(panic)),
    )
    monkeypatch.setattr(lift_rpc, "_send", sent.append)

    with pytest.raises(SystemExit):
        lift_rpc._serve()

    diagnostic = sent[0]["error"]["data"]
    assert diagnostic["exception_type"] == panic_type
    assert diagnostic["diagnostic"] == {
        "owner": "rpc-role-map",
        "observed": "fixture",
        "requested": "role-correct answer",
        "fix": "preserve the concrete tree taxonomy",
    }


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


def test_fact_construction_rewrites_enclosing_temporal_scope(tmp_path: Path) -> None:
    """A fact is constructed from the rewritten function, not its raw Assert.

    This is the bad twin for the old caller-side bypass: direct
    ``assert_node.sugar()`` left ``x`` symbolic even though the preceding
    assignment had already fixed it to 2.
    """
    (tmp_path / "temporal.py").write_text(
        "def add(a):\n    return a\n\n"
        "def test_bound():\n    x = 2\n    assert add(x) == 2\n",
        encoding="utf-8",
    )
    file_key = _enumerate("source_files", tmp_path)["nodes"][0]["memento"]
    functions = {
        n["memento"]["function_name"]: n["memento"]
        for n in _enumerate("functions", tmp_path, at=file_key)["nodes"]
    }
    assertion = _enumerate("call_sites", tmp_path, at=functions["test_bound"])["nodes"][
        0
    ]["memento"]
    result = _enumerate("facts", tmp_path, at=assertion, seek=True)
    formula = result["nodes"][0]["payload"]
    call = formula["args"][0]
    argument = call["args"][0]
    assert call["name"] == "call:add"
    assert argument["kind"] == "const"
    assert argument["value"] == 2


def test_universe_cue_rewrites_temporal_callee_alias(tmp_path: Path) -> None:
    """Callee discovery and argument application see the same rewritten tree."""
    (tmp_path / "temporal_alias.py").write_text(
        "def target(a):\n    return a\n\n"
        "def test_alias():\n    callee = target\n    assert callee(1) == 1\n",
        encoding="utf-8",
    )
    file_key = _enumerate("source_files", tmp_path)["nodes"][0]["memento"]
    functions = {
        n["memento"]["function_name"]: n["memento"]
        for n in _enumerate("functions", tmp_path, at=file_key)["nodes"]
    }
    call_site = _enumerate("call_sites", tmp_path, at=functions["test_alias"])["nodes"][
        0
    ]["memento"]

    universe = _enumerate("universe", tmp_path, at=call_site, seek=True)
    assert universe["gaps"] == []
    assert len(universe["nodes"]) == 1
    assert universe["nodes"][0]["memento"]["source_function_name"] == "target"

    implication = _enumerate("implications", tmp_path, at=call_site, seek=True)
    assert implication["gaps"] == []
    assert implication["nodes"][0]["audit"]["targetSymbol"] == "call:target"


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
    assert demand["sourceContract"]["name"].startswith("add#euf#")
    assert demand["sourceContract"]["name"].endswith("::assertion")
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
