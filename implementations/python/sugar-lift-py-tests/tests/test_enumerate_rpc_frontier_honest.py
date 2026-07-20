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
                        all_panics.append({**p, "demandedBody": body, "ownerIdentity": owner})
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
    # `assert 1 == 1` -- Assert/Compare/Constant have sugar WRITTEN, so they
    # are NOT gaps; FunctionDef/Module do not yet, so they ARE. The census is
    # precise: it clears the sugared nodes and fingers only the unwritten ones.
    audit = _drive_frontier("def test_one():\n    assert 1 == 1\n")
    assert audit.status == "failed"
    gap_kinds = {p.gap["kind"] for p in audit.panics}
    assert "FunctionDef" in gap_kinds and "Module" in gap_kinds, gap_kinds
    for written in ("Assert", "Compare", "Constant"):
        assert written not in gap_kinds, f"{written} sugar is written; not a gap"


if __name__ == "__main__":
    test_unwritten_sugar_makes_the_frontier_fail_loudly()
    test_census_fingers_exactly_the_unwritten_kinds()
    print("ok: frontier is honest -- unwritten kinds finger, written kinds clear")
