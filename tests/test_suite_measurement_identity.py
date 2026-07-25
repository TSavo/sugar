"""Discrimination teeth for suite measurement identity law.

Covers the entire law, not merely field population:

- sourceStamp resolution failure → red
- null extras hash → red
- identity stripped from final report while env prep looked green → red
- contradictory commit/stamp testimony → red
- fully populated matching identity → green
- ``{"unavailable": ...}`` counts as unresolved, not truthy
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

from suite_measurement_identity import (  # noqa: E402
    identity_errors,
    is_authoritative,
    is_resolved_source_stamp,
    is_unavailable,
    promote_identity_fields,
    rewrite_promoted,
)

COMMIT = "d94f67a3149ea2aceee4f9a8cff0397b6f6d374a"
OTHER = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
STAMP = {
    "algorithm": "sha256-of-sugar_source_stamp-preimage",
    "value": "b" * 64,
    "preimageBytes": 12,
}
EXTRAS = "c" * 64
ENV_HASH = "d" * 64


def _base_report(**overrides):
    collected = ["t.py::test_a", "t.py::test_b"]
    report = {
        "schemaVersion": 1,
        "measuredCommit": COMMIT,
        "sourceStamp": dict(STAMP),
        "testExtraInputHash": EXTRAS,
        "environmentIdentityHash": ENV_HASH,
        "environmentIdentity": {
            "schemaVersion": 1,
            "sourceStamp": dict(STAMP),
            "dependencyAuthority": {
                "package": "sugar-lift-py-tests",
                "testExtraInputHash": EXTRAS,
            },
            "environmentIdentityHash": ENV_HASH,
        },
        "runnerIdentity": {"githubSha": COMMIT},
        "leaseRecord": {"measuredCommit": COMMIT, "acquired": True},
        "collectedNodeIds": list(collected),
        "executedOrderNodeIds": list(collected),
        "passedNodeIds": list(collected),
        "failedNodeIds": [],
        "errorNodeIds": [],
        "skippedNodeIds": [],
        "xfailedNodeIds": [],
        "xpassedNodeIds": [],
        "collectionErrorNodeIds": [],
        "notReportedNodeIds": [],
        "counts": {
            "collected": 2,
            "passed": 2,
            "failed": 0,
            "error": 0,
            "skipped": 0,
            "xfailed": 0,
            "xpassed": 0,
            "collectionError": 0,
            "notReported": 0,
        },
    }
    report.update(overrides)
    return report


def test_unavailable_object_is_unresolved_not_truthy():
    stamp = {
        "unavailable": "CalledProcessError: cargo missing",
        "stderr": "FileNotFoundError: cargo",
    }
    assert is_unavailable(stamp)
    assert not is_resolved_source_stamp(stamp)
    # A truthy-dict check would green this — the law forbids that.
    assert stamp  # still truthy as a Python object
    errors = identity_errors(
        _base_report(
            sourceStamp=stamp,
            environmentIdentity={
                "sourceStamp": stamp,
                "dependencyAuthority": {"testExtraInputHash": EXTRAS},
                "environmentIdentityHash": ENV_HASH,
            },
        ),
        require_commit=COMMIT,
    )
    assert any("sourceStamp: unresolved" in e for e in errors)


def test_force_source_stamp_resolution_failure_is_red():
    report = _base_report(
        sourceStamp={"unavailable": "forced stamp failure"},
        environmentIdentity={
            "sourceStamp": {"unavailable": "forced stamp failure"},
            "dependencyAuthority": {"testExtraInputHash": EXTRAS},
            "environmentIdentityHash": ENV_HASH,
        },
    )
    assert not is_authoritative(report, require_commit=COMMIT)


def test_force_null_extras_hash_is_red():
    report = _base_report(
        testExtraInputHash=None,
        environmentIdentity={
            "sourceStamp": dict(STAMP),
            "dependencyAuthority": {"testExtraInputHash": None},
            "environmentIdentityHash": ENV_HASH,
        },
    )
    # Drop top-level extras so only nested null remains.
    report.pop("testExtraInputHash", None)
    errors = identity_errors(report, require_commit=COMMIT)
    assert any("testExtraInputHash" in e for e in errors)


def test_strip_identity_from_final_report_is_red():
    """Env prep green, final report identity gone → red (post-serialization)."""
    report = _base_report()
    report.pop("environmentIdentity", None)
    report.pop("sourceStamp", None)
    report.pop("testExtraInputHash", None)
    report.pop("environmentIdentityHash", None)
    errors = identity_errors(report, require_commit=COMMIT)
    assert errors
    assert not is_authoritative(report, require_commit=COMMIT)


def test_contradictory_commit_testimony_is_red():
    report = _base_report(
        measuredCommit=COMMIT,
        leaseRecord={"measuredCommit": OTHER, "acquired": True},
        runnerIdentity={"githubSha": COMMIT},
    )
    errors = identity_errors(report, require_commit=COMMIT)
    assert any("contradicts" in e for e in errors)


def test_require_commit_mismatch_is_red():
    report = _base_report(measuredCommit=COMMIT)
    errors = identity_errors(report, require_commit=OTHER)
    assert any("contradicts required" in e for e in errors)


def test_fully_populated_matching_identity_is_green():
    report = _base_report()
    assert identity_errors(report, require_commit=COMMIT) == []
    assert is_authoritative(report, require_commit=COMMIT)


def test_promote_does_not_lift_unavailable_stamp():
    report = _base_report(
        environmentIdentity={
            "sourceStamp": {"unavailable": "no cargo"},
            "dependencyAuthority": {"testExtraInputHash": EXTRAS},
            "environmentIdentityHash": ENV_HASH,
        }
    )
    report.pop("sourceStamp", None)
    promoted = promote_identity_fields(report)
    assert "sourceStamp" not in promoted or is_unavailable(promoted.get("sourceStamp"))
    assert promoted.get("testExtraInputHash") == EXTRAS


def test_rewrite_promoted_post_serialization_round_trip(tmp_path: Path):
    path = tmp_path / "suite-report.json"
    path.write_text(json.dumps(_base_report(), indent=2) + "\n", encoding="utf-8")
    reread = rewrite_promoted(str(path))
    assert reread["measuredCommit"] == COMMIT
    assert reread["sourceStamp"]["value"] == STAMP["value"]
    assert reread["testExtraInputHash"] == EXTRAS
    # Gate on the on-disk bytes, not the intermediate.
    disk = json.loads(path.read_text(encoding="utf-8"))
    assert identity_errors(disk, require_commit=COMMIT) == []


def test_conservation_break_is_red():
    report = _base_report()
    report["counts"]["failed"] = 99
    errors = identity_errors(report, require_commit=COMMIT)
    assert any("conservation" in e for e in errors)


def test_gate_cli_reds_unavailable_stamp(tmp_path: Path, monkeypatch):
    from suite_measurement_identity_gate import main as gate_main

    report = _base_report(
        sourceStamp={"unavailable": "no cargo"},
        environmentIdentity={
            "sourceStamp": {"unavailable": "no cargo"},
            "dependencyAuthority": {"testExtraInputHash": EXTRAS},
            "environmentIdentityHash": ENV_HASH,
        },
    )
    path = tmp_path / "suite-report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    assert (
        gate_main(["--report", str(path), "--require-commit", COMMIT, "--promote"]) == 1
    )


def test_gate_cli_greens_full_identity(tmp_path: Path):
    from suite_measurement_identity_gate import main as gate_main

    path = tmp_path / "suite-report.json"
    path.write_text(json.dumps(_base_report()), encoding="utf-8")
    assert (
        gate_main(["--report", str(path), "--require-commit", COMMIT, "--promote"]) == 0
    )


def test_current_attended_shape_from_30175741263_is_provisional_not_authoritative():
    """The attended run's sourceStamp was {"unavailable": ...} — not authoritative."""
    report = _base_report(
        measuredCommit=None,
        sourceStamp={
            "unavailable": (
                "CalledProcessError: cargo missing (attended run 30175741263 shape)"
            )
        },
        environmentIdentity={
            "sourceStamp": {
                "unavailable": "CalledProcessError: cargo missing",
            },
            "dependencyAuthority": {"testExtraInputHash": EXTRAS},
            "environmentIdentityHash": ENV_HASH,
        },
        leaseRecord={"measuredCommit": COMMIT, "acquired": True},
    )
    report.pop("measuredCommit", None)
    # After promote, commit may come from leaseRecord.
    promoted = promote_identity_fields(report)
    # Still red: stamp unavailable.
    assert not is_authoritative(promoted, require_commit=COMMIT)
    assert any(
        "sourceStamp" in e for e in identity_errors(promoted, require_commit=COMMIT)
    )
