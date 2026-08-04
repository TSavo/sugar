"""Teeth: core matrix loops fan out; enrollment proves completeness."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from repo_root_test_support import resolve_repo_root

ROOT = resolve_repo_root()
CI = ROOT / ".github/workflows/ci.yml"
CLAIM_SHARDS = ROOT / "tools/claim_mass_tripwire_shards.py"
CLAIM_ATTEND = ROOT / "tools/claim_mass_tripwire_attendance.py"
FMT_SHARDS = ROOT / "tools/python_format_shards.py"
FMT_ATTEND = ROOT / "tools/python_format_attendance.py"


def test_claim_mass_pins_are_independent_and_matrixed() -> None:
    names = subprocess.check_output(
        [sys.executable, str(CLAIM_SHARDS), "--list"],
        cwd=ROOT,
        text=True,
    ).split()
    assert len(names) >= 4
    assert "datetime" in names
    matrix = json.loads(
        subprocess.check_output(
            [sys.executable, str(CLAIM_SHARDS), "--emit-matrix-json"],
            cwd=ROOT,
            text=True,
        )
    )
    assert set(matrix["pin"]) == set(names)
    text = CI.read_text(encoding="utf-8")
    assert "claim-mass-tripwires" in text
    assert "claim-mass-attendance" in text
    assert "claim_mass_tripwire_attendance" in text
    # Not a single core-matrix serial make target anymore
    assert "target: test-claim-mass-tripwires" not in text


def test_claim_mass_matrix_uses_the_source_stamp_setup_entrance_once() -> None:
    workflow = CI.read_text(encoding="utf-8")
    job = workflow.split("  claim-mass-tripwires:\n", 1)[1].split(
        "\n  claim-mass-attendance:", 1
    )[0]

    setup = "uses: ./.github/actions/setup-rust-cache"
    preflight = "id: claim_mass_source_stamp_preconditions"
    run_pin = "name: Run pin ${{ matrix.pin }}"
    assert job.count(setup) == 1
    assert job.count(preflight) == 1
    assert job.count("tools/sugar_source_stamp.py") == 1
    assert job.index(setup) < job.index(preflight) < job.index(run_pin)
    assert (
        "steps.claim_mass_source_stamp_preconditions.outcome == 'success'" in job
    )


def test_claim_mass_missing_pin_is_unmeasured(tmp_path: Path) -> None:
    names = subprocess.check_output(
        [sys.executable, str(CLAIM_SHARDS), "--list"],
        cwd=ROOT,
        text=True,
    ).split()
    # attend all but last
    for name in names[:-1]:
        d = tmp_path / f"claim-mass-{name}"
        d.mkdir()
        (d / "claim-mass-body.json").write_text(
            json.dumps(
                {
                    "measurementClass": "claim-mass-tripwires",
                    "pin": name,
                    "measuredCommit": "abc",
                    "exitCode": 0,
                }
            ),
            encoding="utf-8",
        )
    proc = subprocess.run(
        [
            sys.executable,
            str(CLAIM_ATTEND),
            "--reports-dir",
            str(tmp_path),
            "--require-commit",
            "abc",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    assert proc.returncode != 0
    assert "UNMEASURED" in proc.stdout or names[-1] in proc.stdout


def test_python_format_is_matrixed_by_package() -> None:
    units = subprocess.check_output(
        [sys.executable, str(FMT_SHARDS), "--list"],
        cwd=ROOT,
        text=True,
    ).splitlines()
    assert len(units) >= 5
    text = CI.read_text(encoding="utf-8")
    assert "python-format-attendance" in text
    assert "target: test-python-format" not in text


def test_indivisible_core_entries_remain_single_jobs() -> None:
    text = CI.read_text(encoding="utf-8")
    assert "check-lift-refusal-vocabulary" in text
    assert "check-fleet-claim-contract" in text
    assert "self-attest" in text


def test_coretests_not_redesigned_here() -> None:
    """Do not reintroduce coretests fan-out in this PR (Rust out of campaign)."""
    text = CI.read_text(encoding="utf-8")
    assert "coretests-invariants" not in text or "matrix" in text
    # Fan-out tools for coretests must not appear
    assert "coretests_invariants_shards" not in text
