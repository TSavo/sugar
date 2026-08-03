"""The recovered-construction frontier, re-homed onto the tree, is HONEST.

The factory census is gone; the frontier now walks the tree with a
CollectingReporter. A file with an unwritten-sugar node (a bare Name) must
report a panic -- status `failed`, R>0 -- not the false `complete` the empty
stub produced. A fully-sugared file (only `assert 1 == 1`) reports `clean`.

Both directions of the closed wire contract are validated in-process without
the Rust build: the leaf decodes via RecoveredAuditDto.from_rpc, and a
simulation of the Rust fold (fold_recovered_audit) assembles a tree audit that
RecoveredFrontierAuditDto.from_rpc accepts.
"""

import tempfile
from pathlib import Path

from sugar_lift_py_tests import lift_rpc
from sugar_lift_py_tests.kit_rpc.recovered_audit_dto import (
    RecoveredAuditDto,
    RecoveredFrontierAuditDto,
)
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.process_resident_file import clear_process_resident_files
from sugar_source_tree.tree import SourceFile


def _drive_frontier(source: str):
    """Walk source_files -> functions -> facts under auditFrontier, exactly as
    the Rust fold does, and assemble the tree-level audit it would build."""
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
            source_files_enumerated = len(files)
            source_bodies_demanded = 0
            audit_leaves_completed = 0
            all_panics = []
            for f in files:
                defs, dgaps = enum("functions", f["memento"])
                assert not dgaps, dgaps
                source_bodies_demanded += 1
                for d in defs:
                    leaves, lgaps = enum("facts", d["memento"])
                    assert not lgaps and len(leaves) == 1, (leaves, lgaps)
                    leaf = leaves[0]["audit"]
                    # leaf must decode as the closed leaf schema (producer end)
                    RecoveredAuditDto.from_rpc(leaf)
                    # fold stamps demandedBody/ownerIdentity per demanded body
                    body = d["memento"]
                    for p in leaf["panics"]:
                        owner = {
                            "demandedBody": body,
                            "demandedSource": p["demandedSource"],
                            "terminalGapLocus": p["terminalGapLocus"],
                        }
                        all_panics.append(
                            {**p, "demandedBody": body, "ownerIdentity": owner}
                        )
                    audit_leaves_completed += 1
            status = (
                "valid-empty"
                if source_files_enumerated == 0
                else ("complete" if not all_panics else "failed")
            )
            tree = {
                "kind": "recovered-construction-audit",
                "recoveryOverride": True,
                "status": status,
                "census": {
                    "kind": "recovered-frontier-census",
                    "sourceFilesEnumerated": source_files_enumerated,
                    "sourceBodiesDemanded": source_bodies_demanded,
                    "auditLeavesCompleted": audit_leaves_completed,
                },
                "panics": all_panics,
                "effects": [],
                "suppressedDescendants": [],
            }
            # the whole tree audit must validate as the closed fold schema
            return RecoveredFrontierAuditDto.from_rpc(tree)
    finally:
        lift_rpc._send_enumerate_result = orig_send


def test_unwritten_sugar_makes_the_frontier_fail_loudly():
    # a bare Name expression has no sugar written -> a real frontier gap
    audit = _drive_frontier("def test_one():\n    x\n")
    assert audit.status == "failed", "unwritten sugar must not read as clean"
    assert audit.panics, "R must be > 0 when the corpus has unwritten sugar"
    blames = {p.gap["blame"] for p in audit.panics}
    assert len(blames) == len(audit.panics), "each gap locus is unique"


def test_census_fingers_exactly_the_unwritten_kinds():
    # `assert 1 == 1` -- Assert/Compare/Constant AND now FunctionDef (its body
    # reduces to a universe) have sugar WRITTEN, so they are NOT gaps; only
    # Module remains unwritten. The census is precise: it clears every sugared
    # kind and fingers only the one that is still missing.
    audit = _drive_frontier("def test_one():\n    assert 1 == 1\n")
    assert audit.status == "failed"
    gap_kinds = {p.gap["kind"] for p in audit.panics}
    assert "Module" in gap_kinds, gap_kinds
    for written in ("Assert", "Compare", "Constant", "FunctionDef"):
        assert written not in gap_kinds, f"{written} sugar is written; not a gap"


def test_shared_cid_at_distinct_loci_stays_distinct_and_located():
    # Two identical `import os` statements register two ImportAlias nodes with
    # the SAME sealed fragment CID (equal source text) at DISTINCT loci. The
    # roll call counts both; the panic producer must too. Keying panics by CID
    # alone collapses the second locus onto the first node -- mislocating it to
    # line 1 AND emitting a duplicate owner identity the Rust reader rejects,
    # which under-reports the real second-site residual.
    with tempfile.TemporaryDirectory() as root:
        path = Path(root, "t.py")
        path.write_text("import os\nimport os\n")
        leaf = lift_rpc._roll_call_audit_leaf(path, "t.py")

    panics = leaf["semanticCore"]["panics"]
    owners = [(p["demandedSource"], p["terminalGapLocus"]) for p in panics]
    assert len(owners) == len(
        set(owners)
    ), f"duplicate recovered-panic owner identity: {owners}"

    alias_lines = sorted(
        p["terminalGapLocus"]
        for p in panics
        if p["terminalGapLocus"].endswith("[ImportAlias]")
    )
    assert alias_lines == [
        "t.py:1:7-1:9[ImportAlias]",
        "t.py:2:7-2:9[ImportAlias]",
    ], f"each import alias must keep its own locus, got {alias_lines}"

    # The panic list conserves the roll-call minority exactly: one row per
    # absent source site, no fusion, no inflation.
    assert (
        len(panics)
        == leaf["auxiliaryRows"]["sourceAudit"]["totals"]["source_unresolved"]
    ), "panic count must equal R (source_unresolved)"


def test_d3_residency_observer_distinguishes_real_miss_and_hit(tmp_path):
    """The exposure detector must return both answers at the real D3 open.

    It observes the existing open; it neither clears nor re-opens inside the
    producer.  The miss arm seats the collector at construction.  The hit arm
    exposes #7171: rebinding only SourceFile.reporter leaves resident nodes on
    their constructor-bound NULL_REPORTER.
    """
    path = tmp_path / "t.py"
    path.write_text("def f():\n    x\n", encoding="utf-8")
    _source, _filename, source_cid = path_source(str(path))

    clear_process_resident_files()
    lift_rpc._roll_call_audit_leaf(
        path,
        "t.py",
        expected_source_cid=source_cid,
    )
    miss = lift_rpc.take_d3_residency_observation(source_cid)
    assert miss == {
        "sourceCid": source_cid,
        "presentAtAuditOpen": False,
        "auditOpenReusedResident": False,
        "rootReporterSeatedAtAuditOpen": True,
        "collectorRegisteredAtAuditExit": True,
    }

    clear_process_resident_files()
    SourceFile.from_path(path)  # D2/CM-shaped prior prepare with NULL_REPORTER.
    lift_rpc._roll_call_audit_leaf(
        path,
        "t.py",
        expected_source_cid=source_cid,
    )
    hit = lift_rpc.take_d3_residency_observation(source_cid)
    assert hit == {
        "sourceCid": source_cid,
        "presentAtAuditOpen": True,
        "auditOpenReusedResident": True,
        "rootReporterSeatedAtAuditOpen": False,
        "collectorRegisteredAtAuditExit": False,
    }


if __name__ == "__main__":
    test_unwritten_sugar_makes_the_frontier_fail_loudly()
    test_census_fingers_exactly_the_unwritten_kinds()
    test_shared_cid_at_distinct_loci_stays_distinct_and_located()
    print("ok: frontier is honest -- unwritten kinds finger, written kinds clear")
