"""The recovered-construction frontier, re-homed onto the tree, is HONEST.

The factory census is gone; the frontier now walks the tree with a
CollectingReporter. A file with a node that refuses at construction (a
``del`` of a tuple target) must report a panic -- status `failed`, R>0, the
refusal by its own name -- not the false `complete` the empty stub produced.
A fully-sugared file (only `assert 1 == 1`) reports `clean`.

The leaf is demanded the way the board door's D3 demand asks for it (one facts
leaf sought at each file's memento under auditFrontier) and validated
in-process without the Rust build: it decodes via RecoveredAuditDto.from_rpc.
"""

import tempfile
from dataclasses import dataclass
from pathlib import Path

from sugar_lift_py_tests import lift_rpc
from sugar_lift_py_tests.kit_rpc.recovered_audit_dto import (
    RecoveredAuditDto,
    RecoveredConstructionPanicDto,
)
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.process_resident_file import (
    clear_process_resident_files,
    prepare_count_for,
)


@dataclass(frozen=True)
class _Frontier:
    status: str
    panics: list[RecoveredConstructionPanicDto]


def _drive_frontier(source: str) -> _Frontier:
    """Demand source_files, then one facts leaf per file under auditFrontier,
    exactly as the board door's D3 demand does."""
    captured = {}
    orig_send = lift_rpc._send_enumerate_result
    lift_rpc._send_enumerate_result = lambda mid, nodes, gaps, **kw: captured.update(
        nodes=nodes, gaps=gaps
    )
    A = {"auditFrontier": True}
    try:
        with tempfile.TemporaryDirectory() as root:
            Path(root, "t.py").write_text(source)

            def enum(level, at=None):
                lift_rpc._handle_enumerate(
                    1,
                    {
                        "level": level,
                        "workspace_root": root,
                        "at": at,
                        "seek": level == "facts",
                        "options": A,
                    },
                )
                return captured["nodes"], captured["gaps"]

            files, fgaps = enum("source_files")
            assert not fgaps, fgaps
            all_panics = []
            for f in files:
                leaves, lgaps = enum("facts", f["memento"])
                assert not lgaps and len(leaves) == 1, (leaves, lgaps)
                leaf = leaves[0]["audit"]
                semantic_core = leaf.get("semanticCore") or leaf
                # leaf must decode as the closed leaf schema (producer end)
                all_panics.extend(RecoveredAuditDto.from_rpc(semantic_core).panics)
            return _Frontier(
                status="failed" if all_panics else "clean", panics=all_panics
            )
    finally:
        lift_rpc._send_enumerate_result = orig_send


def test_a_construction_refusal_makes_the_frontier_fail_by_name():
    # ``del (a, b)``: a delete whose target is not a name, attribute or
    # subscript is not lowered, and ``Delete`` refuses it by name at
    # construction.  (A bare Name expression, this test's old fixture, has had
    # its sugar written since.)  The frontier is failed, and the refusal
    # reaches it under its own name at the node that refused -- never as an
    # unaccounted absentee.
    audit = _drive_frontier(
        "def test_one():\n    a = 1\n    b = 2\n    del (a, b)\n"
    )
    assert audit.status == "failed", "a construction refusal must not read as clean"
    assert audit.panics, "R must be > 0 when the corpus has a refusal"
    blames = {p.gap["blame"] for p in audit.panics}
    assert len(blames) == len(audit.panics), "each gap locus is unique"
    named = [p for p in audit.panics if p.gap["nodeKind"] == "Delete"]
    assert len(named) == 1, [p.gap for p in audit.panics]
    assert named[0].gap["kind"] == "SugarNotWritten"
    assert named[0].gap["owner"] == "Delete._construct_sugar"
    assert not any(
        p.gap["kind"] == "UnaccountedConstruction" for p in audit.panics
    ), "a named refusal explains every node it stopped"


def test_a_fully_sugared_file_reads_clean():
    # `assert 1 == 1` -- Module, FunctionDef, Assert, Compare and Constant all
    # have their sugar written, so the roll has no absentee and the census
    # fingers nothing.
    audit = _drive_frontier("def test_one():\n    assert 1 == 1\n")
    assert audit.status == "clean"
    assert audit.panics == []


def test_shared_cid_at_distinct_loci_stays_distinct_without_fake_panics():
    # Two identical `import os` statements register two ImportAlias nodes with
    # the SAME sealed fragment CID (equal source text) at DISTINCT loci. The
    # roll call counts both, and each answers at its own locus where its
    # statement constructs (the statement absorbs it as the spelling of the
    # name it binds).  Two answers sharing one CID never fuse into one.
    with tempfile.TemporaryDirectory() as root:
        path = Path(root, "t.py")
        path.write_text("import os\nimport os\n")
        leaf = lift_rpc._roll_call_audit_leaf(path, "t.py", root=Path(root))

    panics = leaf["semanticCore"]["panics"]
    owners = [(p["demandedSource"], p["terminalGapLocus"]) for p in panics]
    assert len(owners) == len(
        set(owners)
    ), f"duplicate recovered-panic owner identity: {owners}"

    source_audit = leaf["auxiliaryRows"]["sourceAudit"]
    alias_loci = sorted(
        (row["locus"]["line"], row["locus"]["col"], row["source_cid"], row["status"])
        for row in source_audit["loci"]
        if row["kind"] == "ImportAlias"
    )
    assert [(line, col) for line, col, _cid, _status in alias_loci] == [
        (1, 7),
        (2, 7),
    ]
    assert alias_loci[0][2] == alias_loci[1][2], "equal text keeps one content CID"
    assert [status for *_rest, status in alias_loci] == ["warranted", "warranted"]
    assert not any(
        panic["gap"].get("nodeKind") == "ImportAlias" for panic in panics
    ), "an alias its statement absorbed is never a silent absentee"


def test_d3_residency_observer_distinguishes_real_miss_and_hit(tmp_path):
    """The exposure detector must return both answers at the real D3 open.

    It observes the existing open; it neither clears nor re-opens inside the
    producer.  The miss arm seats the collector at construction.  The hit arm
    proves the D3 consumer re-seats the already prepared nodes without paying a
    second prepare, so both paths testify through the same collector.
    """
    path = tmp_path / "t.py"
    path.write_text("def f():\n    x\n", encoding="utf-8")
    _source, _filename, source_cid = path_source(str(path))

    clear_process_resident_files()
    lift_rpc._roll_call_audit_leaf(
        path,
        "t.py",
        root=tmp_path,
        expected_source_cid=source_cid,
    )
    miss = lift_rpc.take_d3_residency_observation(source_cid)
    assert prepare_count_for(source_cid) == 1
    assert miss == {
        "sourceCid": source_cid,
        "presentAtAuditOpen": False,
        "auditOpenReusedResident": False,
        "rootReporterSeatedAtAuditOpen": True,
        "collectorRegisteredAtAuditExit": True,
    }

    clear_process_resident_files()
    # D2-shaped prior open with NULL_REPORTER, through the one opener.
    lift_rpc.open_source_file_for_construction(path, root=tmp_path)
    assert prepare_count_for(source_cid) == 1
    lift_rpc._roll_call_audit_leaf(
        path,
        "t.py",
        root=tmp_path,
        expected_source_cid=source_cid,
    )
    hit = lift_rpc.take_d3_residency_observation(source_cid)
    assert prepare_count_for(source_cid) == 1
    assert hit == {
        "sourceCid": source_cid,
        "presentAtAuditOpen": True,
        "auditOpenReusedResident": True,
        "rootReporterSeatedAtAuditOpen": True,
        "collectorRegisteredAtAuditExit": True,
    }


if __name__ == "__main__":
    test_a_construction_refusal_makes_the_frontier_fail_by_name()
    test_a_fully_sugared_file_reads_clean()
    test_shared_cid_at_distinct_loci_stays_distinct_without_fake_panics()
    print("ok: frontier is honest -- unwritten kinds finger, written kinds clear")
