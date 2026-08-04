"""Discrimination teeth for explicit, reversible showcase retirement."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from repo_root_test_support import resolve_repo_root

ROOT = resolve_repo_root()
sys.path.insert(0, str(ROOT / "tools"))

import showcase_scope  # noqa: E402

MANIFEST = ROOT / ".github/showcase-retirements.json"
ATTEND = ROOT / "tools/showcase_shard_attendance.py"
CI = ROOT / ".github/workflows/ci.yml"
MAKEFILE = ROOT / "Makefile"
REASON = "out of scope per scope ruling - Java"

EXPECTED_BY_SHARD = {
    0: {
        "examples/java-testng-consistency/run.sh",
        "examples/java-b64-tails/run.sh",
        "examples/java-callbind-consistency/run.sh",
        "examples/java-panama-bridge/run.sh",
        "examples/java-pattern-regex/run.sh",
    },
    1: {
        "examples/java-codec-universe/run.sh",
        "examples/java-abs-universe/run.sh",
        "examples/java-instance-universe/run.sh",
        "examples/java-abs-model/run.sh",
    },
    2: {
        "examples/java-assertion-consistency/run.sh",
        "examples/java-urlsafe-seam/run.sh",
        "examples/java-bound-federation/run.sh",
        "examples/java-voltron/run.sh",
        "examples/java-mt-reference/run.sh",
    },
    3: {
        "examples/java-forall-loop/run.sh",
        "examples/java-b64-strong/run.sh",
        "examples/java-abs-bound/run.sh",
        "examples/java-abs-flagship/run.sh",
        "examples/java-crc32-universe/run.sh",
    },
}
EXPECTED = set().union(*EXPECTED_BY_SHARD.values())


def _write_script(
    path: Path,
    marker: str,
    exit_code: int,
    *,
    testify_subject: bool | None = None,
) -> None:
    if testify_subject is None:
        testify_subject = exit_code == 0
    testimony = (
        'printf \'%s\\n\' "$SHOWCASE_SUBJECT_ID" > "$SHOWCASE_SUBJECT_WITNESS"\n'
        if testify_subject
        else ""
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "#!/usr/bin/env sh\n"
        f"printf '%s\\n' {json.dumps(marker)} >> \"$SHOWCASE_TRACE\"\n"
        f"{testimony}"
        f"exit {exit_code}\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _write_manifest(path: Path, rows: list[dict[str, str]]) -> None:
    path.write_text(
        json.dumps({"schemaVersion": 1, "retirements": rows}, indent=2) + "\n",
        encoding="utf-8",
    )


def _retirement(path: str) -> dict[str, str]:
    return {
        "path": path,
        "language": "java",
        "outcome": "retired",
        "reason": REASON,
        "assertion": "fixture Java assertion",
    }


def _run_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    retirements: list[dict[str, str]],
) -> tuple[int, dict[str, object], str]:
    java = "examples/java-fixture/run.sh"
    python = "examples/python-fixture/run.sh"
    _write_script(tmp_path / java, "java-executed", 0)
    _write_script(tmp_path / python, "python-executed", 9)
    manifest = tmp_path / "retirements.json"
    _write_manifest(manifest, retirements)
    trace = tmp_path / "trace.txt"
    monkeypatch.setenv("SHOWCASE_TRACE", str(trace))
    receipt = tmp_path / "scope.json"

    returncode = showcase_scope.run_shard(
        repo_root=tmp_path,
        manifest_path=manifest,
        enrolled=[java, python],
        shard_count=1,
        shard_index=0,
        attr_dir=tmp_path / "logs",
        receipt_path=receipt,
    )
    return (
        returncode,
        json.loads(receipt.read_text(encoding="utf-8")),
        trace.read_text(encoding="utf-8"),
    )


def test_manifest_is_exact_java_only_authority_with_5_4_5_5_shards() -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    rows = payload["retirements"]
    assert len(rows) == 19
    assert {row["path"] for row in rows} == EXPECTED
    assert all(row["language"] == "java" for row in rows)
    assert all(row["outcome"] == "retired" for row in rows)
    assert all(row["reason"] == REASON for row in rows)
    assert all(row["assertion"].strip() for row in rows)

    roster = showcase_scope.makefile_showcase_roster(ROOT / "Makefile")
    retirements = showcase_scope.load_manifest(MANIFEST, roster)
    for shard, expected in EXPECTED_BY_SHARD.items():
        plan = showcase_scope.partition(
            roster, retirements, shard_count=4, shard_index=shard
        )
        assert {row["path"] for row in plan["retired"]} == expected
        assert plan["counts"]["retired"] == len(expected)
        assert (
            plan["counts"]["executed"] + plan["counts"]["retired"]
            == plan["counts"]["enrolled"]
        )


@pytest.mark.parametrize(
    ("mutation", "crime"),
    [
        ({"reason": ""}, "missing retirement reason"),
        ({"language": "python"}, "non-Java retirement"),
        ({"outcome": "passed"}, "unsupported retirement outcome"),
        ({"assertion": ""}, "missing retired assertion"),
        ({"path": "examples/not-enrolled/run.sh"}, "not enrolled"),
    ],
)
def test_malformed_retirement_refuses_by_name(
    tmp_path: Path, mutation: dict[str, str], crime: str
) -> None:
    enrolled = ["examples/java-fixture/run.sh"]
    row = _retirement(enrolled[0])
    row.update(mutation)
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, [row])
    with pytest.raises(showcase_scope.ScopeRefusal, match=crime):
        showcase_scope.load_manifest(manifest, enrolled)


def test_duplicate_retirement_refuses_by_name(tmp_path: Path) -> None:
    enrolled = ["examples/java-fixture/run.sh"]
    manifest = tmp_path / "manifest.json"
    row = _retirement(enrolled[0])
    _write_manifest(manifest, [row, row])
    with pytest.raises(showcase_scope.ScopeRefusal, match="duplicate retirement"):
        showcase_scope.load_manifest(manifest, enrolled)


def test_retired_does_not_execute_while_active_executes_and_stays_red(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    returncode, receipt, trace = _run_fixture(
        tmp_path,
        monkeypatch,
        [_retirement("examples/java-fixture/run.sh")],
    )
    assert returncode != 0
    assert "java-executed" not in trace
    assert "python-executed" in trace
    assert receipt["counts"] == {
        "enrolled": 2,
        "executed": 1,
        "retired": 1,
        "passed": 0,
        "failed": 1,
        "unmeasured": 0,
    }
    assert receipt["outcomes"][0]["outcome"] == "retired"
    assert receipt["outcomes"][0]["reason"] == REASON
    assert receipt["outcomes"][1]["outcome"] == "failed"
    assert receipt["outcomes"][1]["exitCode"] == 9


def test_removing_manifest_entry_executes_the_showcase_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    returncode, receipt, trace = _run_fixture(tmp_path, monkeypatch, [])
    assert returncode != 0
    assert trace.splitlines() == ["java-executed", "python-executed"]
    assert [row["outcome"] for row in receipt["outcomes"]] == ["passed", "failed"]
    assert receipt["counts"]["retired"] == 0
    assert receipt["counts"]["executed"] == receipt["counts"]["enrolled"] == 2


def test_retirement_cannot_be_fabricated_by_a_passing_showcase(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = "examples/python-pass/run.sh"
    _write_script(tmp_path / script, "passed", 0)
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, [])
    trace = tmp_path / "trace.txt"
    monkeypatch.setenv("SHOWCASE_TRACE", str(trace))
    receipt = tmp_path / "scope.json"
    assert (
        showcase_scope.run_shard(
            repo_root=tmp_path,
            manifest_path=manifest,
            enrolled=[script],
            shard_count=1,
            shard_index=0,
            attr_dir=tmp_path / "logs",
            receipt_path=receipt,
        )
        == 0
    )
    body = json.loads(receipt.read_text(encoding="utf-8"))
    assert body["outcomes"] == [
        {
            "path": script,
            "outcome": "passed",
            "exitCode": 0,
            "subjectWitness": {"schemaVersion": 1, "subjectId": script},
        }
    ]


def test_exit_zero_without_subject_witness_is_unmeasured_not_passed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = "examples/python-skip/run.sh"
    _write_script(
        tmp_path / script,
        "SKIP: fixture subject unavailable",
        0,
        testify_subject=False,
    )
    manifest = tmp_path / "manifest.json"
    _write_manifest(manifest, [])
    trace = tmp_path / "trace.txt"
    monkeypatch.setenv("SHOWCASE_TRACE", str(trace))
    receipt = tmp_path / "scope.json"

    assert (
        showcase_scope.run_shard(
            repo_root=tmp_path,
            manifest_path=manifest,
            enrolled=[script],
            shard_count=1,
            shard_index=0,
            attr_dir=tmp_path / "logs",
            receipt_path=receipt,
        )
        != 0
    )
    body = json.loads(receipt.read_text(encoding="utf-8"))
    assert body["counts"] == {
        "enrolled": 1,
        "executed": 1,
        "retired": 0,
        "passed": 0,
        "failed": 0,
        "unmeasured": 1,
    }
    assert body["outcomes"] == [
        {
            "path": script,
            "outcome": "unmeasured",
            "exitCode": 0,
            "reason": "subject-witness-absent",
        }
    ]


def test_consumer_refuses_exit_zero_pass_without_subject_witness() -> None:
    body = {
        "measurementClass": "test-showcases",
        "shardIndex": 0,
        "shardCount": 1,
        "measuredCommit": "abc",
        "exitCode": 0,
        "showcaseCounts": {
            "enrolled": 1,
            "executed": 1,
            "retired": 0,
            "passed": 1,
            "failed": 0,
            "unmeasured": 0,
        },
        "showcaseOutcomes": [
            {
                "path": "examples/python-pass/run.sh",
                "outcome": "passed",
                "exitCode": 0,
            }
        ],
    }

    with pytest.raises(
        showcase_scope.ScopeRefusal,
        match="passed showcase lacks authenticated subject witness",
    ):
        showcase_scope.validate_shard_body(body)


def test_conservation_refuses_missing_showcase() -> None:
    body = {
        "measurementClass": "test-showcases",
        "shardIndex": 0,
        "shardCount": 1,
        "measuredCommit": "abc",
        "exitCode": 0,
        "showcaseCounts": {
            "enrolled": 2,
            "executed": 1,
            "retired": 0,
            "passed": 1,
            "failed": 0,
            "unmeasured": 0,
        },
        "showcaseOutcomes": [
            {
                "path": "examples/python-pass/run.sh",
                "outcome": "passed",
                "exitCode": 0,
                "subjectWitness": {
                    "schemaVersion": 1,
                    "subjectId": "examples/python-pass/run.sh",
                },
            }
        ],
    }
    with pytest.raises(showcase_scope.ScopeRefusal, match="conservation"):
        showcase_scope.validate_shard_body(body)


def test_scope_receipt_seals_distinct_outcomes_in_ci_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, scope_receipt, _ = _run_fixture(
        tmp_path,
        monkeypatch,
        [_retirement("examples/java-fixture/run.sh")],
    )
    output = tmp_path / "showcase-shard-body.json"
    body = showcase_scope.seal_shard_body(
        scope_receipt,
        measured_commit="abc",
        exit_code=1,
        output_path=output,
    )
    assert json.loads(output.read_text(encoding="utf-8")) == body
    assert [row["outcome"] for row in body["showcaseOutcomes"]] == [
        "retired",
        "failed",
    ]
    assert body["showcaseCounts"]["retired"] == 1
    assert body["showcaseCounts"]["failed"] == 1


def test_makefile_routes_full_roster_through_scope_owner() -> None:
    text = MAKEFILE.read_text(encoding="utf-8")
    target = text.split("test-showcases:", 1)[1].split("# --- CI alias", 1)[0]
    assert "tools/showcase_scope.py run" in target
    assert ".github/showcase-retirements.json" in target
    assert "SHOWCASE_SCOPE_RECEIPT" in target
    assert "for s in $(SHOWCASE_RUNS)" not in target
    assert "showcase-scope active execution: PASS" in target


def test_every_active_showcase_testifies_subject_completion() -> None:
    roster = showcase_scope.makefile_showcase_roster(MAKEFILE)
    retirements = showcase_scope.load_manifest(MANIFEST, roster)
    marker = (
        "printf '%s\\n' \"${SHOWCASE_SUBJECT_ID:?}\" > "
        "\"${SHOWCASE_SUBJECT_WITNESS:?}\""
    )
    active = [path for path in roster if path not in retirements]

    assert len(active) == 46
    for path in active:
        assert (ROOT / path).read_text(encoding="utf-8").rstrip().endswith(marker), path


def test_python_urlsafe_real_skip_cannot_testify_subject_completion() -> None:
    text = (ROOT / "examples/python-urlsafe-seam/run.sh").read_text(encoding="utf-8")
    skip = 'if [ "$provenance_rc" -eq 42 ]; then\n  exit 0\nfi'
    good = "run_twin good discharged"
    bad = "run_twin bad refused"
    witness = (
        "printf '%s\\n' \"${SHOWCASE_SUBJECT_ID:?}\" > "
        "\"${SHOWCASE_SUBJECT_WITNESS:?}\""
    )

    assert text.index(skip) < text.index(good) < text.index(bad) < text.index(witness)


def test_ci_seals_scope_receipt_into_shard_body() -> None:
    text = CI.read_text(encoding="utf-8")
    showcase_job = text.split("  showcases:", 1)[1].split("  showcase-attendance:", 1)[
        0
    ]
    assert "SHOWCASE_SCOPE_RECEIPT" in showcase_job
    assert "tools/showcase_scope.py seal-body" in showcase_job
    assert "showcaseOutcomes" not in showcase_job
    assert "showcaseCounts" not in showcase_job


def test_attendance_refuses_unconserved_body_as_unmeasured(tmp_path: Path) -> None:
    body = {
        "measurementClass": "test-showcases",
        "shardIndex": 0,
        "shardCount": 1,
        "measuredCommit": "abc",
        "exitCode": 0,
        "showcaseCounts": {
            "enrolled": 2,
            "executed": 1,
            "retired": 0,
            "passed": 1,
            "failed": 0,
            "unmeasured": 0,
        },
        "showcaseOutcomes": [
            {
                "path": "examples/python-pass/run.sh",
                "outcome": "passed",
                "exitCode": 0,
                "subjectWitness": {
                    "schemaVersion": 1,
                    "subjectId": "examples/python-pass/run.sh",
                },
            }
        ],
    }
    (tmp_path / "body.json").write_text(json.dumps(body), encoding="utf-8")
    proc = subprocess.run(
        [
            sys.executable,
            str(ATTEND),
            "--reports-dir",
            str(tmp_path),
            "--shard-count",
            "1",
            "--require-commit",
            "abc",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert proc.returncode != 0
    assert "R_showcase_shard_attendance = 1" in proc.stdout
    assert "conservation" in proc.stderr


def test_attendance_stays_red_for_attended_active_failure(tmp_path: Path) -> None:
    for shard in range(4):
        outcomes = [
            {
                "path": f"examples/java-retired-{shard}/run.sh",
                "outcome": "retired",
                "language": "java",
                "reason": REASON,
                "assertion": "retired fixture",
            },
            {
                "path": f"examples/python-active-{shard}/run.sh",
                "outcome": "failed" if shard == 2 else "passed",
                "exitCode": 7 if shard == 2 else 0,
                **(
                    {
                        "subjectWitness": {
                            "schemaVersion": 1,
                            "subjectId": f"examples/python-active-{shard}/run.sh",
                        }
                    }
                    if shard != 2
                    else {}
                ),
            },
        ]
        directory = tmp_path / f"shard-{shard}"
        directory.mkdir()
        (directory / "body.json").write_text(
            json.dumps(
                {
                    "measurementClass": "test-showcases",
                    "shardIndex": shard,
                    "shardCount": 4,
                    "measuredCommit": "abc",
                    "exitCode": 7 if shard == 2 else 0,
                    "showcaseCounts": {
                        "enrolled": 2,
                        "executed": 1,
                        "retired": 1,
                        "passed": 0 if shard == 2 else 1,
                        "failed": 1 if shard == 2 else 0,
                        "unmeasured": 0,
                    },
                    "showcaseOutcomes": outcomes,
                }
            ),
            encoding="utf-8",
        )

    proc = subprocess.run(
        [
            sys.executable,
            str(ATTEND),
            "--reports-dir",
            str(tmp_path),
            "--shard-count",
            "4",
            "--require-commit",
            "abc",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert proc.returncode != 0
    assert "attended: `4`" in proc.stdout
    assert "R_showcase_shard_attendance = 0" in proc.stdout
    assert "shard-02: exitCode=7 (showcase red)" in proc.stderr
