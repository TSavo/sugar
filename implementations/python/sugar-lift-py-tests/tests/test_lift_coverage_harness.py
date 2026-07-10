"""Lift-coverage harness (#4013): majority assertions vs minority bodies.

Two divergent axes — never one folded coverage number.

* Majority: silently_unaccounted is RED (lifter bug if > 0).
* Minority: un_asserted is VISIBLE scope (not a bug; dig is assertion-triggered).

Headline from the pre-build probe on statistics (battleaxe):
  on-disk asserts stated=4, report accounted=1, silently_unaccounted=3.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from sugar_lift_py_tests.idd.collect_panic_audit import (
    _hermetic_env_for_sugar_command,
    _prepare_audit_workspace,
    _resolve_audit_sugar_bin,
    _resolve_installed_package_path,
)
from sugar_lift_py_tests.idd.lift_coverage_accounting import (
    account_lift_coverage,
    paint_lines,
)
from sugar_lift_py_tests.idd.lift_coverage_census import (
    census_paths,
    census_source,
)

ROOT = Path(__file__).resolve().parents[4]


def _run_lift_report_json(workspace: Path) -> dict:
    sugar = _resolve_audit_sugar_bin(None)
    cmd = [os.fspath(sugar), "lift", "--report", "--json", str(workspace)]
    env = _hermetic_env_for_sugar_command(cmd)
    completed = subprocess.run(
        cmd, cwd=ROOT, text=True, capture_output=True, check=False, env=env
    )
    assert completed.returncode == 0, (
        f"lift --report failed exit={completed.returncode}\n"
        f"stdout={completed.stdout[:1500]}\nstderr={completed.stderr[:1500]}"
    )
    text = (completed.stdout or "").strip()
    start = text.find("{")
    assert start >= 0, f"no JSON in lift report stdout:\n{text[:1500]}"
    return json.loads(text[start:])


def _stage_and_report(source_file: Path) -> tuple[dict, Path]:
    with tempfile.TemporaryDirectory(prefix="lift-cov-test-") as td:
        ws = Path(td) / source_file.stem
        _prepare_audit_workspace(source_file, ROOT, ws, audit_only=False)
        report = _run_lift_report_json(ws)
        return report, ws


# ---------------------------------------------------------------------------
# Unit: independent census + partition (no sugar binary)
# ---------------------------------------------------------------------------


def test_independent_census_counts_asserts_and_bodies() -> None:
    src = (
        "def dug():\n"
        "    assert 1 == 1\n"
        "def idle():\n"
        "    return 0\n"
    )
    disk = census_source(src, file="t.py")
    assert disk.asserts and len(disk.asserts) == 1
    assert disk.asserts[0].line == 2
    assert len(disk.bodies) == 2
    names = {b.name for b in disk.bodies}
    assert names == {"dug", "idle"}


def test_majority_silent_measured_not_hardcoded() -> None:
    """Discrimination (a): unaccounted construct → silently_unaccounted > 0."""
    src = (
        "def f():\n"
        "    assert True\n"
        "    assert False  # second assert never cited by empty report\n"
    )
    disk = census_source(src, file="t.py")
    # Empty report → every assert is silent.
    cov = account_lift_coverage(disk, {})
    assert cov.majority.stated == 2
    assert cov.majority.lifted_cited == 0
    assert cov.majority.silently_unaccounted == 2
    assert not cov.majority.is_zero if hasattr(cov.majority, "is_zero") else True
    assert cov.majority.to_json()["is_zero"] is False
    lines = {a["line"] for a in cov.majority.silent_loci}
    assert lines == {2, 3}


def test_majority_cited_assert_is_not_silent() -> None:
    src = "def f():\n    assert 1 == 1\n"
    disk = census_source(src, file="t.py")
    fake_report = {
        "sourceAudits": [
            {
                "file": "t.py",
                "contract": "t::f::assert:2:4::assertion",
                "role": "python.identity-assertion-sugar",
                "loci": [
                    {
                        "file": "t.py",
                        "line": 2,
                        "col": 4,
                        "status": "warranted",
                        "ast_kind": "Assert",
                    }
                ],
            }
        ]
    }
    cov = account_lift_coverage(disk, fake_report)
    assert cov.majority.stated == 1
    assert cov.majority.lifted_cited == 1
    assert cov.majority.silently_unaccounted == 0
    assert cov.majority.to_json()["is_zero"] is True


def test_minority_unasserted_body_is_visible_not_red() -> None:
    """Discrimination (b): body with no assertion appears in minority report."""
    src = (
        "def claimed():\n"
        "    assert 1 == 1\n"
        "def orphan():\n"
        "    return 42\n"
    )
    disk = census_source(src, file="t.py")
    fake_report = {
        "sourceAudits": [
            {
                "file": "t.py",
                "sourceFunctionName": "claimed",
                "contract": "t::claimed::assert:2:4::assertion",
                "loci": [
                    {
                        "file": "t.py",
                        "line": 2,
                        "col": 4,
                        "status": "warranted",
                        "ast_kind": "Assert",
                    }
                ],
            }
        ]
    }
    cov = account_lift_coverage(disk, fake_report)
    assert cov.minority.present == 2
    assert cov.minority.dug >= 1
    assert cov.minority.un_asserted >= 1
    un_names = {b["name"] for b in cov.minority.un_asserted_loci}
    assert "orphan" in un_names
    # Minority has no red gate field.
    assert cov.minority.to_json()["gate"] is None


def test_minority_assert_moves_body_out_of_unasserted() -> None:
    """Discrimination (b2): adding an assertion targeting a body → it leaves un_asserted."""
    before = (
        "def later():\n"
        "    return 1\n"
    )
    after = (
        "def later():\n"
        "    assert 1 == 1\n"
        "    return 1\n"
    )
    disk_before = census_source(before, file="t.py")
    disk_after = census_source(after, file="t.py")
    cov_before = account_lift_coverage(disk_before, {})
    cov_after = account_lift_coverage(
        disk_after,
        {
            "sourceAudits": [
                {
                    "file": "t.py",
                    "sourceFunctionName": "later",
                    "loci": [
                        {
                            "file": "t.py",
                            "line": 2,
                            "col": 4,
                            "status": "warranted",
                            "ast_kind": "Assert",
                        }
                    ],
                }
            ]
        },
    )
    assert any(b["name"] == "later" for b in cov_before.minority.un_asserted_loci)
    assert not any(b["name"] == "later" for b in cov_after.minority.un_asserted_loci)
    assert any(b["name"] == "later" for b in cov_after.minority.dug_loci)


def test_line_paint_marks_silent_and_minority() -> None:
    src = (
        "def claimed():\n"
        "    assert 1 == 1\n"
        "def orphan():\n"
        "    return 0\n"
        "def silent_fn():\n"
        "    assert 2 == 2\n"
    )
    disk = census_source(src, file="t.py")
    cov = account_lift_coverage(
        disk,
        {
            "sourceAudits": [
                {
                    "file": "t.py",
                    "sourceFunctionName": "claimed",
                    "loci": [
                        {
                            "file": "t.py",
                            "line": 2,
                            "col": 4,
                            "status": "warranted",
                            "ast_kind": "Assert",
                        }
                    ],
                }
            ]
        },
    )
    paint = paint_lines(src, cov, file="t.py")
    by_line = {row["line"]: row["bucket"] for row in paint}
    assert by_line[2] == "lifted+cited"
    assert by_line[6] == "silently-unaccounted"
    assert by_line[3] == "minority-un-asserted"


# ---------------------------------------------------------------------------
# Integration: statistics vendor on battleaxe (real sugar lift --report)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def statistics_report() -> dict:
    path = _resolve_installed_package_path("statistics")
    assert path.is_file() and path.name == "statistics.py", path
    with tempfile.TemporaryDirectory(prefix="lift-cov-stats-") as td:
        ws = Path(td) / "statistics"
        _prepare_audit_workspace(path, ROOT, ws, audit_only=False)
        return _run_lift_report_json(ws)


def test_statistics_report_emits_dual_axis_lift_coverage(statistics_report: dict) -> None:
    cov = statistics_report.get("liftCoverage") or statistics_report.get("lift_coverage")
    assert cov is not None, (
        "lift --report must emit liftCoverage line items (#4013); "
        f"keys={sorted(statistics_report.keys())}"
    )
    assert cov.get("kind") == "lift-coverage"
    majority = cov["majority"]
    minority = cov["minority"]
    totals = cov["totals"]
    # Dual totals present and divergent (never one folded number).
    assert "majority_stated" in totals
    assert "majority_silently_unaccounted" in totals
    assert "minority_present" in totals
    assert "minority_un_asserted" in totals
    assert majority["axis"] == "majority-assertions"
    assert minority["axis"] == "minority-bodies"
    assert minority["gate"] is None
    assert majority["gate"] == "silently_unaccounted == 0"


def test_statistics_majority_headline_delta_matches_probe(statistics_report: dict) -> None:
    """Re-paste the pre-build headline: stated vs silently_unaccounted.

    Probe (battleaxe): on-disk asserts=4, report accounted=1, silent=3.
    """
    path = _resolve_installed_package_path("statistics")
    disk = census_paths([path], root=path.parent)
    cov = statistics_report["liftCoverage"]
    maj = cov["majority"]
    assert maj["stated"] == len(disk.asserts) == 4
    # At least the one _coerce assert is cited; three remain silent (headline).
    assert maj["lifted_cited"] >= 1
    assert maj["silently_unaccounted"] == 3, (
        f"expected 3 silent asserts on statistics; got {maj['silently_unaccounted']}: "
        f"{maj['silent_loci']}"
    )
    silent_lines = sorted(a["line"] for a in maj["silent_loci"])
    assert silent_lines == [200, 237, 323], silent_lines
    # Totals headline
    assert cov["totals"]["majority_stated"] == 4
    assert cov["totals"]["majority_silently_unaccounted"] == 3


def test_statistics_majority_silent_unaccounted_gate_is_zero(
    statistics_report: dict,
) -> None:
    """Totality ratchet: RED while any assert is silently unaccounted.

    This is the mandatory-fix instrument for #4013 majority axis. Current
    statistics residual is 3 (lines 200, 237, 323) — the test FAILS loud until
    those asserts are lifted+cited or refused-loud. Do not fabricate zero.
    """
    maj = statistics_report["liftCoverage"]["majority"]
    silent = int(maj["silently_unaccounted"])
    if silent != 0:
        loci = maj.get("silent_loci") or []
        detail = "\n".join(
            f"  - {a.get('file')}:{a.get('line')}  {a.get('preview', '')}"
            for a in loci[:20]
        )
        pytest.fail(
            f"majority silently_unaccounted={silent} (must be 0).\n"
            f"Silent assert loci (mandatory-fix finding):\n{detail}\n"
            f"Probe headline: stated=4 accounted=1 delta=3 on statistics.py"
        )


def test_statistics_minority_bodies_are_visible_scope(statistics_report: dict) -> None:
    """Minority: present bodies, dug subset, un_asserted remainder — not red."""
    path = _resolve_installed_package_path("statistics")
    disk = census_paths([path], root=path.parent)
    mino = statistics_report["liftCoverage"]["minority"]
    assert mino["present"] == len(disk.bodies) == 58
    assert mino["dug"] + mino["un_asserted"] == mino["present"]
    # Most of statistics is un-asserted scope (no claim targets those bodies).
    assert mino["un_asserted"] > 0
    assert mino["gate"] is None
    # At least one un_asserted locus is named with file:line.
    sample = mino["un_asserted_loci"][0]
    assert "file" in sample and "line" in sample and "name" in sample


def test_discrimination_inject_unaccounted_construct_reds_majority(tmp_path: Path) -> None:
    """Live lift: source with 2 asserts, only one cited-capable shape still
    measures silent residue via independent census (unit twin above is pure).

    This uses account_lift_coverage with a partial report to prove the field
    moves when a construct is dropped from the report.
    """
    src = "def f():\n    assert 1 == 1\n    assert 2 == 2\n"
    disk = census_source(src, file="inj.py")
    full = {
        "sourceAudits": [
            {
                "file": "inj.py",
                "loci": [
                    {
                        "file": "inj.py",
                        "line": 2,
                        "col": 4,
                        "status": "warranted",
                        "ast_kind": "Assert",
                    },
                    {
                        "file": "inj.py",
                        "line": 3,
                        "col": 4,
                        "status": "warranted",
                        "ast_kind": "Assert",
                    },
                ],
            }
        ]
    }
    partial = {
        "sourceAudits": [
            {
                "file": "inj.py",
                "loci": [
                    {
                        "file": "inj.py",
                        "line": 2,
                        "col": 4,
                        "status": "warranted",
                        "ast_kind": "Assert",
                    }
                ],
            }
        ]
    }
    cov_full = account_lift_coverage(disk, full)
    cov_partial = account_lift_coverage(disk, partial)
    assert cov_full.majority.silently_unaccounted == 0
    assert cov_partial.majority.silently_unaccounted == 1
    assert cov_partial.majority.silent_loci[0]["line"] == 3
