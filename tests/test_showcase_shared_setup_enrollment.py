"""Teeth: showcase shared setup + per-shard enrollment (no merge hub)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CI = ROOT / ".github/workflows/ci.yml"
ATTEND = ROOT / "tools/showcase_shard_attendance.py"


def test_showcase_prepare_builds_one_wheelhouse_for_all_shards() -> None:
    text = CI.read_text(encoding="utf-8")
    assert "showcase-prepare" in text
    assert "showcase-wheelhouse" in text
    assert "pip wheel" in text
    # Shards consume the artifact — not four independent network resolves of
    # the same package set as the only install path.
    assert "Download shared wheelhouse" in text
    assert "--no-index --find-links" in text or "--find-links" in text


def test_four_shards_remain_for_genuine_per_shard_work() -> None:
    text = CI.read_text(encoding="utf-8")
    assert "shard: [0, 1, 2, 3]" in text
    assert "SHOWCASE_SHARD_INDEX" in text
    assert "make test-showcases" in text


def test_missing_showcase_shard_is_unmeasured(tmp_path: Path) -> None:
    for i in range(3):
        d = tmp_path / f"showcase-shard-{i}"
        d.mkdir()
        (d / "showcase-shard-body.json").write_text(
            json.dumps(
                {
                    "measurementClass": "test-showcases",
                    "shardIndex": i,
                    "shardCount": 4,
                    "measuredCommit": "abc",
                    "exitCode": 0,
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
    assert "shard-03" in proc.stdout or "UNMEASURED" in proc.stdout


def test_full_showcase_roster_is_green(tmp_path: Path) -> None:
    for i in range(4):
        d = tmp_path / f"showcase-shard-{i}"
        d.mkdir()
        (d / "body.json").write_text(
            json.dumps(
                {
                    "measurementClass": "test-showcases",
                    "shardIndex": i,
                    "shardCount": 4,
                    "measuredCommit": "abc",
                    "exitCode": 0,
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
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_acid_test_gates_on_enrollment_not_raw_matrix() -> None:
    text = CI.read_text(encoding="utf-8")
    # Post-#7021: no prepare job. Acid gates on enrollment, not the raw matrix.
    acid = text.split("acid-test:")[1]
    needs_block = acid.split("runs-on:")[0]
    assert "showcase-attendance" in needs_block
    assert "needs.showcase-attendance.result" in acid
    assert "needs.showcases.result" not in acid
    # Job-level needs must not reintroduce the deleted prepare job.
    assert "- prepare" not in needs_block
    assert "needs: prepare" not in needs_block
    assert "needs: [prepare" not in needs_block
