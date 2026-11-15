# SPDX-License-Identifier: MIT OR Apache-2.0
"""Part 6, Phase 2: `sugar.enumerate` (`protocol/specs/2026-07-08-enumeration-protocol.md`).

Exercises `_handle_enumerate` directly (in-process, no subprocess spawn).
The Rust side drives this handler only through mint's one door
(`fold_enumerate_source_tree`: source_files -> universe); the assertion ->
fact descent is gone (#7757 entry 5 / item 25), and so are the `call_sites`
level and the universe seek by a call-site cue (#7757).
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.repo_root import resolve_repo_root

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
    """The board door's D3 demand: one facts leaf sought at the file memento."""
    file_key = next(
        node["memento"]
        for node in _enumerate("source_files", workspace)["nodes"]
        if node["memento"]["file"] == file
    )
    return _enumerate(
        "facts",
        workspace,
        at=file_key,
        seek=True,
        options={"auditFrontier": True},
    )["nodes"][0]["audit"]


def test_audit_frontier_is_refused_below_facts(project: Path) -> None:
    """`sugar lift --audit-frontier` walked functions under auditFrontier; the
    Python kit answers auditFrontier at `facts` only (#7806)."""
    file_key = _enumerate("source_files", project)["nodes"][0]["memento"]
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
                    "level": "functions",
                    "workspace_root": str(project),
                    "at": file_key,
                    "seek": False,
                    "options": {"auditFrontier": True},
                },
            },
        )
    finally:
        lift_rpc._send = original_send
    assert len(captured) == 1, captured
    error = captured[0]["error"]
    assert error["code"] == -32602
    assert "auditFrontier is answered at level 'facts' only" in error["message"]


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
                    blame=absent.fragment,
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
    gap = leaf["panics"][0]["gap"]
    assert gap["kind"] == "UnaccountedConstruction"
    assert leaf["sourceAudit"]["totals"]["source_unresolved"] == 1
    # The absentee reaches the board as an authenticated refusal, the same
    # payload every refusal by name carries, so the board decodes it as a
    # construction-panic terminal at the absentee's own coordinate.
    assert gap["observedEventType"] == "sugar_source_tree.panic.UnaccountedConstruction"
    assert gap["coordinate"] == gap["blame"]
    assert gap["blame"].endswith(f"[{gap['nodeKind']}]")
    for field in ("owner", "observed", "requested", "fix", "entrance"):
        assert isinstance(gap[field], str) and gap[field], field
    assert isinstance(gap["construction_trace"], list) and gap["construction_trace"]


def test_roll_call_audit_uses_one_construction_and_one_discharge(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-home monolithic-fold and partial-demand laws onto one module roll."""
    from sugar_lift_py_tests import lift_rpc
    import sugar_source_tree.roll_call as roll_call

    calls = {"construction": 0, "discharge": 0}
    original_open_at_seat = lift_rpc._open_at_seat
    original_discharge = roll_call.discharge

    def counted_open_at_seat(*args, **kwargs):
        # The opener's first stage; the step-3 reads (the With rows, the
        # lexical import pass) open it with no context and construct nothing.
        if kwargs.get("construction_context") is not None:
            calls["construction"] += 1
        return original_open_at_seat(*args, **kwargs)

    def counted_discharge(source_file):
        calls["discharge"] += 1
        return original_discharge(source_file)

    monkeypatch.setattr(lift_rpc, "_open_at_seat", counted_open_at_seat)
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
        blame="role.py:1:0",
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
    # The facts leaf opens through the CONSTRUCTION door, never the bare one.
    monkeypatch.setattr(
        lift_rpc,
        "open_source_file_for_construction",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(panic),
    )
    monkeypatch.setattr(lift_rpc, "_send", sent.append)

    # The refusal is the request's typed error; the resident keeps serving and
    # returns when the input ends.
    lift_rpc._serve()

    diagnostic = sent[0]["error"]["data"]
    assert diagnostic["exception_type"] == panic_type
    assert diagnostic["diagnostic"] == {
        "owner": "rpc-role-map",
        "blame": "role.py:1:0",
        "observed": "fixture",
        "requested": "role-correct answer",
        "fix": "preserve the concrete tree taxonomy",
    }


@pytest.mark.parametrize("level", ["source_files", "functions", "universe"])
def test_a_seek_off_the_board_door_leaf_is_refused_by_name(
    project: Path, level: str
) -> None:
    """Every level is a scan (#7757). The seeks that read one node back (a
    file, a function, a universe by its own memento or by a call-site cue)
    had no driver; a seek is refused by name, never answered with the scan."""
    file_memento = _enumerate("source_files", project)["nodes"][0]["memento"]
    response = _enumerate_raw(level, project, at=file_memento, seek=True)
    assert "result" not in response, response
    assert response["error"]["code"] == -32602
    assert "auditFrontier" in response["error"]["message"]


def test_functions_finds_both_the_contract_owner_and_the_enclosing_test(
    project: Path,
) -> None:
    """Each ``def`` is named as its source names it. The module-qualified
    spelling is the definition's one symbol, stated on its contract row
    (``bridgeSourceSymbol``, see the universe scan below), never a second
    spelling of the memento's name."""
    file_memento = _enumerate("source_files", project)["nodes"][0]["memento"]
    result = _enumerate("functions", project, at=file_memento)
    names = sorted(
        n["memento"].get("function_name") or n["memento"].get("source_function_name")
        for n in result["nodes"]
    )
    assert names == ["add", "test_add"]


CALLING_SOURCE = """\
def double(x):
    return x + x


def test_double():
    assert double(3) == 6
"""


@pytest.mark.parametrize("level", ["functions", "universe"])
def test_every_level_answers_the_same_when_asked_first(
    tmp_path: Path, level: str
) -> None:
    """One opener: no level's answer depends on which level opened the file first.

    A level that opened its file without the construction context answered
    from whatever tree an earlier level had left process-resident, and refused
    with ``BareConstructionDoor`` when it was the first to ask (#7759).
    """
    from sugar_source_tree.process_resident_file import clear_process_resident_files

    (tmp_path / "dbl.py").write_text(CALLING_SOURCE, encoding="utf-8")
    file_memento = _enumerate("source_files", tmp_path)["nodes"][0]["memento"]

    warm = _enumerate(level, tmp_path, at=file_memento)
    clear_process_resident_files()
    cold = _enumerate(level, tmp_path, at=file_memento)

    assert cold == warm


def test_functions_level_uses_the_canonical_construction_open(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The RPC functions entrance must not mint a second bare SourceFile."""
    opened = []
    real_open = lift_rpc.open_source_file_for_construction

    def observe_open(path, **kwargs):
        source_file = real_open(path, **kwargs)
        opened.append((path, kwargs, source_file.unit.filename))
        return source_file

    monkeypatch.setattr(lift_rpc, "open_source_file_for_construction", observe_open)
    file_memento = _enumerate("source_files", project)["nodes"][0]["memento"]

    result = _enumerate("functions", project, at=file_memento)

    assert len(result["nodes"]) == 2
    assert len(opened) == 1
    path, kwargs, filename = opened[0]
    assert path == project / "mathy.py"
    assert kwargs["root"] == project
    # The one opener has no way to skip population (#7796).
    assert "populate_derived" not in kwargs
    assert "distribution" not in kwargs
    assert filename == "mathy.py"


def test_facts_is_answered_under_audit_frontier_only(project: Path) -> None:
    """The assertion -> fact descent is gone (#7757 entry 5 / item 25).

    `facts` is the board door's audit leaf; without auditFrontier it is a
    typed refusal, never a second walk of a function's asserts.
    """
    file_memento = _enumerate("source_files", project)["nodes"][0]["memento"]
    response = _enumerate_raw("facts", project, at=file_memento)
    assert response["error"]["code"] == -32602
    assert "auditFrontier" in response["error"]["message"]


def test_the_call_sites_level_is_gone(project: Path) -> None:
    """The cue a universe seek read had no driver (#7757): unknown level."""
    file_memento = _enumerate("source_files", project)["nodes"][0]["memento"]
    response = _enumerate_raw("call_sites", project, at=file_memento)
    assert response["error"]["code"] == -32602
    assert "unknown level" in response["error"]["message"]


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
    assert_closed(_enumerate("universe", project, at=file_memento))


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
    response = _enumerate_raw("functions", project, at={"file": "../outside_secret.py"})
    assert "error" not in response, response
    result = response["result"]
    assert result["nodes"] == []
    assert len(result["gaps"]) == 1
    assert "escapes the workspace root" in result["gaps"][0]["reason"]


def test_enumerate_empty_file_is_an_empty_level_not_an_error(project) -> None:
    """A comments-only file has no source sites: empty level, not -32603."""
    (project / "empty_mod.py").write_text("# nothing here\n", encoding="utf-8")
    response = _enumerate_raw("functions", project, at={"file": "empty_mod.py"})
    assert "error" not in response, response
    assert response["result"]["nodes"] == []


def _function_contracts(nodes) -> list:
    """The function-contract rows of a universe scan.

    A function is one contract row (#7766). The other rows a scan states are
    ``undecided`` members (a call or operation nothing here answers, a
    function refused by name) and a class's ancestry; none of them is a
    second row for a function."""
    return [
        node
        for node in nodes
        if (node["audit"] or {}).get("kind") == "function-contract"
    ]


def test_universe_scan_lists_function_contract_rows(project: Path) -> None:
    """File-level universe scan: one function-contract row per function, named
    as its ``def`` is and stating the definition's one symbol."""
    file_memento = _enumerate("source_files", project)["nodes"][0]["memento"]
    result = _enumerate("universe", project, at=file_memento, seek=False)
    contracts = sorted(
        (node["audit"]["name"], node["audit"].get("bridgeSourceSymbol"))
        for node in _function_contracts(result["nodes"])
    )
    assert contracts == [
        ("add", "python:mathy.add"),
        ("test_add", "python:mathy.test_add"),
    ]
    assert result["gaps"] == []


def test_full_tree_universe_rows_come_only_from_the_one_reduction(
    tmp_path: Path,
) -> None:
    """No second lifter adds rows (#7767): no classShapes, and no `pre = true`
    carrier for a body whose reduction is not a set of arms. A ``panicLoci``
    entry is a halted arm of the function's one reduction (#7766: a halt is
    never dropped), in the one panic-locus shape, and nothing else."""
    from sugar_lift_py_tests.kit_rpc.body_universe_dto import RUNTIME_FAILURE_SITE

    source = (
        resolve_repo_root()
        / "examples/numpy-attribute-safety-showcase/good/src/numpy_box.py"
    ).read_text(encoding="utf-8")
    (tmp_path / "numpy_box.py").write_text(source, encoding="utf-8")

    file_memento = _enumerate("source_files", tmp_path)["nodes"][0]["memento"]
    result = _enumerate("universe", tmp_path, at=file_memento, seek=False)
    audits = [node["audit"] or {} for node in result["nodes"]]

    for row in audits:
        for locus in row.get("panicLoci", ()):
            assert row["kind"] == "function-contract", row
            assert locus["callee"] == RUNTIME_FAILURE_SITE, locus
            assert set(locus) <= {"callee", "file", "line", "argTerm", "guard"}, locus
        assert "classShapes" not in row, row
        provenance = row.get("proofirProvenance") or {}
        assert provenance.get("nodeClass") != "SourceSidecarCarrier", row
    init = next(row for row in audits if row.get("name") == "__init__")
    assert "post" in init


def test_full_tree_universe_omits_empty_source_sidecars(tmp_path: Path) -> None:
    """A class-free completed function must not acquire fabricated testimony."""
    (tmp_path / "identity.py").write_text(
        "def identity(value):\n    return value\n", encoding="utf-8"
    )

    file_memento = _enumerate("source_files", tmp_path)["nodes"][0]["memento"]
    result = _enumerate("universe", tmp_path, at=file_memento, seek=False)

    assert len(result["nodes"]) == 1
    audit = result["nodes"][0]["audit"]
    assert "panicLoci" not in audit
    assert "classShapes" not in audit


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
        # One contract row for the one function. ``a + b`` over two formals
        # waits on a caller's actuals, so the scan also states it as an
        # ``undecided`` member: the only other row kind here.
        (contract,) = _function_contracts(nodes)
        assert all(
            node["audit"]["kind"] == "undecided"
            for node in nodes
            if node is not contract
        ), nodes
        return (
            contract["memento"]["source_cid"],
            contract["audit"]["bridgeSourceSymbol"],
        )

    module_a_once = identity("module_a.py")
    module_b_once = identity("module_b.py")
    module_a_twice = identity("module_a.py")

    assert module_a_once != module_b_once
    assert module_a_once == module_a_twice
    # The qualified spelling is the definition's one symbol.
    assert module_a_once[1] == "python:module_a.add"
    assert module_b_once[1] == "python:module_b.add"
