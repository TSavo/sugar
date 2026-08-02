"""Teeth: coretests live R — no pin, no transcribed constants, UNMEASURED first."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-coretests-invariants.py"
PIN = ROOT / "implementations" / "rust" / "coretests-invariants.json"
MAKEFILE = ROOT / "Makefile"


def _run(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        **kwargs,
    )


def _headline(
    *,
    discharged: int = 10,
    refused: int = 0,
    unclassified: int = 0,
    inactive: int = 0,
    silent: int = 0,
    panicked: int = 0,
    expanded: int = 2,
    cid: str = "blake3-512:" + ("ab" * 64),
) -> str:
    # Accounting identity: raw + expanded - missing = accounted
    # accounted = discharged + refused + unclassified + inactive
    missing = silent
    accounted = discharged + refused + unclassified + inactive
    raw = accounted - expanded + missing
    return f"""==== coretests sweep: delta to stdlib-0 ====
corpus: /fake/coretests/tests
files: 3 (parse_ok 3, parse_fail 0)
assertion surface sites seen: {raw}
  discharged (lifted to FOL):  {discharged:>6}  (0.0%)
  refused  (TERMINAL, source): {refused:>6}  (0.0%)   <-- closed with a damn good reason
  unclassified (lifter WORK):  {unclassified:>6}  (0.0%)   <-- the real roadmap; drive to 0
  inactive (cfg-disabled):     {inactive:>6}  (0.0%)   <-- not in this target's universe
  panicked files (LIFTER GAP): {panicked:>6}           <-- ok
  missing assertions (SILENT): {missing:>6}  (0.0%)   <-- delta target = 0
  callsite-expanded obligations:{expanded:>5}   (source body completed at N call sites)
  accounting identity: {raw} raw surfaces + {expanded} expanded - {missing} missing = {accounted} accounted
test fns: seen 0 / lifted 0

---- refusal reason histogram (the roadmap) ----

assertion multiset cid: {cid}
"""


def test_pin_file_is_deleted_and_makefile_does_not_equality_check() -> None:
    assert not PIN.exists(), (
        "coretests-invariants.json must be deleted — authored counts are not law"
    )
    make = MAKEFILE.read_text(encoding="utf-8")
    assert "coretests-invariants.json" not in make or "There is NO coretests-invariants.json" in make
    assert "--body-out" in SCRIPT.read_text(encoding="utf-8")
    # Old two-arg equality invocation must not be the Makefile path.
    assert "check-coretests-invariants.py /tmp/coretests-hermetic.out implementations/rust/coretests-invariants.json" not in make


def test_incomplete_sweep_is_unmeasured_not_zero(tmp_path: Path) -> None:
    """Pinned zeros must not reappear as Measured zeros on incomplete output."""
    sweep = tmp_path / "partial.out"
    sweep.write_text("==== coretests sweep crashed midway ====\n", encoding="utf-8")
    body_path = tmp_path / "body.json"
    result = _run(
        [
            "--sweep-stdout",
            str(sweep),
            "--body-out",
            str(body_path),
            "--require-commit",
            "abc",
        ]
    )
    assert result.returncode == 2, result.stdout + result.stderr
    body = json.loads(body_path.read_text(encoding="utf-8"))
    assert body["status"] == "Unmeasured"
    assert body["residual"]["R_refused"] is None
    assert body["residual"]["R_inactive"] is None
    assert body["floors"]["R_silent"] is None
    # The forbidden move: seed 1125 / 65 / 0 from the old pin.
    text = body_path.read_text(encoding="utf-8")
    assert "1125" not in text
    assert "10544" not in text


def test_sweep_nonzero_exit_is_unmeasured(tmp_path: Path) -> None:
    sweep = tmp_path / "out.txt"
    sweep.write_text(_headline(), encoding="utf-8")
    body_path = tmp_path / "body.json"
    result = _run(
        [
            "--sweep-stdout",
            str(sweep),
            "--body-out",
            str(body_path),
            "--sweep-exit",
            "1",
        ]
    )
    assert result.returncode == 2
    body = json.loads(body_path.read_text(encoding="utf-8"))
    assert body["status"] == "Unmeasured"


def test_residual_refused_nonzero_is_red_not_green_at_n(tmp_path: Path) -> None:
    sweep = tmp_path / "out.txt"
    # Deliberately not 1125 — any N>0 is red; we do not bless a constant.
    sweep.write_text(_headline(refused=3, inactive=0), encoding="utf-8")
    body_path = tmp_path / "body.json"
    result = _run(
        ["--sweep-stdout", str(sweep), "--body-out", str(body_path)]
    )
    assert result.returncode == 1, result.stdout + result.stderr
    body = json.loads(body_path.read_text(encoding="utf-8"))
    assert body["status"] == "Measured"
    assert body["residual"]["R_refused"] == 3
    assert "R_refused=3" in result.stdout or "R_refused=3" in result.stderr


def test_floor_silent_nonzero_is_hard_red(tmp_path: Path) -> None:
    sweep = tmp_path / "out.txt"
    sweep.write_text(_headline(silent=1), encoding="utf-8")
    body_path = tmp_path / "body.json"
    result = _run(
        ["--sweep-stdout", str(sweep), "--body-out", str(body_path)]
    )
    assert result.returncode == 1
    assert "R_silent" in result.stdout + result.stderr


def test_all_floors_and_residual_zero_is_green(tmp_path: Path) -> None:
    sweep = tmp_path / "out.txt"
    sweep.write_text(_headline(refused=0, inactive=0, silent=0), encoding="utf-8")
    body_path = tmp_path / "body.json"
    result = _run(
        [
            "--sweep-stdout",
            str(sweep),
            "--body-out",
            str(body_path),
            "--require-commit",
            "deadbeef",
        ]
    )
    assert result.returncode == 0, result.stdout + result.stderr
    body = json.loads(body_path.read_text(encoding="utf-8"))
    assert body["status"] == "Measured"
    assert body["floors"]["R_silent"] == 0
    assert body["residual"]["R_refused"] == 0
    assert body["context"]["discharged"] == 10
    assert body["assertion_multiset_cid"].startswith("blake3-512:")
    assert body["bodyCid"].startswith("sha256:")


def test_discharged_is_context_not_an_equality_pin(tmp_path: Path) -> None:
    """discharged may be any measured value; only floors/residual gate."""
    sweep = tmp_path / "out.txt"
    sweep.write_text(
        _headline(discharged=99999, refused=0, inactive=0), encoding="utf-8"
    )
    body_path = tmp_path / "body.json"
    result = _run(
        ["--sweep-stdout", str(sweep), "--body-out", str(body_path)]
    )
    assert result.returncode == 0, result.stdout + result.stderr
    body = json.loads(body_path.read_text(encoding="utf-8"))
    assert body["context"]["discharged"] == 99999


def test_script_never_opens_deleted_pin_path(tmp_path: Path) -> None:
    src = SCRIPT.read_text(encoding="utf-8")
    assert "coretests-invariants.json" not in src or "KILLS" in src
    # No residual default constants from the old pin.
    assert "1125" not in src
    assert "10544" not in src
    assert "prev_unclassified" not in src


def test_cid_drift_vs_previous_measured_is_loud(tmp_path: Path) -> None:
    sweep = tmp_path / "out.txt"
    sweep.write_text(_headline(cid="blake3-512:" + ("cd" * 64)), encoding="utf-8")
    body_path = tmp_path / "body.json"
    prior = {
        "status": "Measured",
        "residual": {"R_refused": 0, "R_inactive": 0},
        "assertion_multiset_cid": "blake3-512:" + ("ab" * 64),
        "bodyCid": "sha256:prior",
    }
    prior_path = tmp_path / "prior.json"
    prior_path.write_text(json.dumps(prior), encoding="utf-8")
    result = _run(
        [
            "--sweep-stdout",
            str(sweep),
            "--body-out",
            str(body_path),
            "--previous-body",
            str(prior_path),
        ]
    )
    assert result.returncode == 1
    assert "assertion_multiset_cid drift" in result.stdout + result.stderr


def test_residual_regression_vs_previous_is_loud(tmp_path: Path) -> None:
    sweep = tmp_path / "out.txt"
    sweep.write_text(_headline(refused=5), encoding="utf-8")
    body_path = tmp_path / "body.json"
    prior = {
        "status": "Measured",
        "residual": {"R_refused": 2, "R_inactive": 0},
        "assertion_multiset_cid": "blake3-512:" + ("ab" * 64),
        "bodyCid": "sha256:prior",
    }
    prior_path = tmp_path / "prior.json"
    prior_path.write_text(json.dumps(prior), encoding="utf-8")
    result = _run(
        [
            "--sweep-stdout",
            str(sweep),
            "--body-out",
            str(body_path),
            "--previous-body",
            str(prior_path),
        ]
    )
    assert result.returncode == 1
    assert "regression R_refused" in result.stdout + result.stderr
