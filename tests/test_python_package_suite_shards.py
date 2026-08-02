"""Teeth for suite shards: deterministic split + enrollment without a shared hub."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHARDS = ROOT / "tools" / "python_package_suite_shards.py"
ATTENDANCE = ROOT / "tools" / "python_package_suite_shard_attendance.py"
WORKFLOW = ROOT / ".github" / "workflows" / "python-package-suite.yml"


def _run(argv: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, *argv],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        **kwargs,
    )


def test_shard_assignment_is_deterministic_and_covers_every_file() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("suite_shards", SHARDS)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)

    files = mod.list_suite_test_files(ROOT)
    assert len(files) >= 100, f"expected a real suite tree, got {len(files)} files"

    count = 32
    covered: list[str] = []
    for i in range(count):
        covered.extend(mod.files_for_shard(files, i, count))

    assert sorted(covered) == sorted(files)
    # Same file always same shard across two pure calls.
    assert mod.files_for_shard(files, 0, count) == mod.files_for_shard(
        files, 0, count
    )
    # Spot-check: a middle file's seat is index % count.
    mid = files[len(files) // 2]
    assert mod.shard_index_for(mid, files, count) == files.index(mid) % count


def test_missing_shard_makes_attendance_red_not_a_smaller_pass() -> None:
    """Lying face: N-1 identity-resolved reports ⇒ UNMEASURED, not green."""
    import tempfile

    from importlib import util

    spec = util.spec_from_file_location(
        "identity_gate", ROOT / "tools" / "python_suite_identity_gate.py"
    )
    # Build minimal identity-valid reports for seats 0..2, omit seat 3 of 4.
    stamp = "blake3-512_" + ("ab" * 64)
    extras = "cd" * 32
    identity = {
        "environmentIdentityHash": "ee" * 32,
        "sourceStamp": {"value": stamp},
        "dependencyAuthority": {
            "testExtraInputHash": extras,
            "declared": {"optional-dependencies": {"test": ["pytest"]}},
        },
    }

    def report(shard: int, count: int = 4) -> dict:
        return {
            "schemaVersion": 1,
            "label": f"python-package-suite-canonical-shard-{shard:02d}",
            "order": "canonical",
            "shardIndex": shard,
            "shardCount": count,
            "measuredCommit": "abc1234",
            "sourceStamp": stamp,
            "testExtraInputHash": extras,
            "environmentIdentityHash": identity["environmentIdentityHash"],
            "binarySourceStamp": stamp,
            "environmentIdentity": identity,
            "runnerIdentity": {"githubSha": "abc1234"},
            "collectedNodeIds": [],
            "executedOrderNodeIds": [],
            "failedNodeIds": [],
            "errorNodeIds": [],
            "skippedNodeIds": [],
            "xfailedNodeIds": [],
            "xpassedNodeIds": [],
            "passedNodeIds": [],
            "collectionErrorNodeIds": [],
            "notReportedNodeIds": [],
            "counts": {
                "collected": 0,
                "passed": 0,
                "failed": 0,
                "error": 0,
                "skipped": 0,
                "xfailed": 0,
                "xpassed": 0,
                "collectionError": 0,
                "notReported": 0,
            },
            "conservation": {
                "collected": 0,
                "verdicts": 0,
                "executedOrder": 0,
                "buckets": {
                    "passed": 0,
                    "failed": 0,
                    "error": 0,
                    "skipped": 0,
                    "xfailed": 0,
                    "xpassed": 0,
                    "notReported": 0,
                },
                "collectionError": 0,
            },
        }

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for i in range(3):  # omit shard 3
            d = root / f"python-package-suite-canonical-shard-{i}"
            d.mkdir()
            (d / "suite-report.json").write_text(
                json.dumps(report(i)) + "\n", encoding="utf-8"
            )
        result = _run(
            [
                str(ATTENDANCE),
                "--reports-dir",
                str(root),
                "--shard-count",
                "4",
                "--require-commit",
                "abc1234",
                "--order",
                "canonical",
            ]
        )
    assert result.returncode != 0, result.stdout
    assert "R_suite_shard_attendance = 1" in result.stdout
    assert "shard-03" in result.stdout
    assert "UNMEASURED" in result.stdout


def test_full_roster_attendance_is_green() -> None:
    import tempfile

    stamp = "blake3-512_" + ("ab" * 64)
    extras = "cd" * 32
    identity = {
        "environmentIdentityHash": "ee" * 32,
        "sourceStamp": {"value": stamp},
        "dependencyAuthority": {
            "testExtraInputHash": extras,
            "declared": {"optional-dependencies": {"test": ["pytest"]}},
        },
    }

    def report(shard: int, count: int = 2) -> dict:
        return {
            "schemaVersion": 1,
            "label": f"python-package-suite-canonical-shard-{shard:02d}",
            "order": "canonical",
            "shardIndex": shard,
            "shardCount": count,
            "measuredCommit": "abc1234",
            "sourceStamp": stamp,
            "testExtraInputHash": extras,
            "environmentIdentityHash": identity["environmentIdentityHash"],
            "binarySourceStamp": stamp,
            "environmentIdentity": identity,
            "runnerIdentity": {"githubSha": "abc1234"},
            "collectedNodeIds": [],
            "executedOrderNodeIds": [],
            "failedNodeIds": [],
            "errorNodeIds": [],
            "skippedNodeIds": [],
            "xfailedNodeIds": [],
            "xpassedNodeIds": [],
            "passedNodeIds": [],
            "collectionErrorNodeIds": [],
            "notReportedNodeIds": [],
            "counts": {
                "collected": 0,
                "passed": 0,
                "failed": 0,
                "error": 0,
                "skipped": 0,
                "xfailed": 0,
                "xpassed": 0,
                "collectionError": 0,
                "notReported": 0,
            },
            "conservation": {
                "collected": 0,
                "verdicts": 0,
                "executedOrder": 0,
                "buckets": {
                    "passed": 0,
                    "failed": 0,
                    "error": 0,
                    "skipped": 0,
                    "xfailed": 0,
                    "xpassed": 0,
                    "notReported": 0,
                },
                "collectionError": 0,
            },
        }

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for i in range(2):
            d = root / f"python-package-suite-canonical-shard-{i}"
            d.mkdir()
            (d / "suite-report.json").write_text(
                json.dumps(report(i)) + "\n", encoding="utf-8"
            )
        result = _run(
            [
                str(ATTENDANCE),
                "--reports-dir",
                str(root),
                "--shard-count",
                "2",
                "--require-commit",
                "abc1234",
                "--order",
                "canonical",
            ]
        )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "R_suite_shard_attendance = 0" in result.stdout


def test_workflow_has_no_shared_suite_report_merge_and_uses_enrollment() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "python_package_suite_shard_attendance" in text
    assert "suite-shard-index" in text or "shard-matrix" in text
    # No merge tool / single shared aggregate path (word "merge" may appear
    # in prose forbidding it — ban the tool and the singleton artifact name).
    assert "python_package_suite_merge" not in text
    assert "suite-report.json" in text  # per-shard path still that filename
    assert "python-package-suite-canonical-shard-" in text
    assert "python_package_suite_shard_attendance" in text
