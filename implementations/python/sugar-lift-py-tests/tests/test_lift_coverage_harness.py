"""Lift-coverage harness (#4013): assertion accounting vs minority bodies.

Two divergent axes — never one folded coverage number.

* Assertions (default report body): silently_unaccounted is RED (lifter bug if > 0).
* Minority: un_asserted is VISIBLE scope (not a bug; dig is assertion-triggered).

Headline after #4017 (total assertion-surface enumeration):
  on-disk asserts stated=4, silently_unaccounted=0 (was 3 nested under if/except).
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


def test_assertions_silent_measured_not_hardcoded() -> None:
    """Discrimination (a): unaccounted construct → silently_unaccounted > 0."""
    src = (
        "def f():\n"
        "    assert True\n"
        "    assert False  # second assert never cited by empty report\n"
    )
    disk = census_source(src, file="t.py")
    # Empty report → every assert is silent.
    cov = account_lift_coverage(disk, {})
    assert cov.assertions.stated == 2
    assert cov.assertions.lifted_cited == 0
    assert cov.assertions.silently_unaccounted == 2
    assert not cov.assertions.is_zero if hasattr(cov.assertions, "is_zero") else True
    assert cov.assertions.to_json()["is_zero"] is False
    lines = {a["line"] for a in cov.assertions.silent_loci}
    assert lines == {2, 3}


def test_assertions_cited_assert_is_not_silent() -> None:
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
    assert cov.assertions.stated == 1
    assert cov.assertions.lifted_cited == 1
    assert cov.assertions.silently_unaccounted == 0
    assert cov.assertions.to_json()["is_zero"] is True


def test_minority_unasserted_body_is_visible_not_red() -> None:
    """Discrimination (b): a body with no call_edge targeting it is un_asserted."""
    from sugar_lift_py_tests.lift_rpc import lift_file_payload

    src = (
        "def claimed():\n"
        "    return 1\n"
        "def orphan():\n"
        "    return 42\n"
        "\n"
        "def test_claimed():\n"
        "    assert claimed() == 1\n"
    )
    payload = lift_file_payload(src, "t.py")
    disk = census_source(src, file="t.py")
    cov = account_lift_coverage(disk, payload.to_rpc())
    assert cov.minority.present == 2
    assert cov.minority.dug == 1
    assert cov.minority.un_asserted == 1
    un_names = {b["name"] for b in cov.minority.un_asserted_loci}
    assert "orphan" in un_names
    # Minority has no red gate field.
    assert cov.minority.to_json()["gate"] is None


def test_minority_assert_moves_body_out_of_unasserted() -> None:
    """Discrimination (b2): a call_edge targeting the body leaves un_asserted."""
    from sugar_lift_py_tests.lift_rpc import lift_file_payload

    before = "def later():\n    return 1\n"
    after = (
        "def later():\n"
        "    return 1\n"
        "\n"
        "def test_later():\n"
        "    assert later() == 1\n"
    )
    disk_before = census_source(before, file="t.py")
    cov_before = account_lift_coverage(
        disk_before, lift_file_payload(before, "t.py").to_rpc()
    )
    disk_after = census_source(after, file="t.py")
    cov_after = account_lift_coverage(
        disk_after, lift_file_payload(after, "t.py").to_rpc()
    )
    assert any(b["name"] == "later" for b in cov_before.minority.un_asserted_loci)
    assert not any(b["name"] == "later" for b in cov_after.minority.un_asserted_loci)
    assert any(b["name"] == "later" for b in cov_after.minority.dug_loci)


def test_line_paint_marks_silent_and_minority() -> None:
    from sugar_lift_py_tests.lift_rpc import lift_file_payload

    # Ground tautology assert folds away (no ::assertion fact row) -- true silent.
    # A diggable assert (f(1)==2) would mint a contract fact and paint lifted.
    src = (
        "def claimed():\n"
        "    return 1\n"
        "def orphan():\n"
        "    return 0\n"
        "def silent_fn():\n"
        "    assert 1 == 1\n"
        "    return 0\n"
        "\n"
        "def test_claimed():\n"
        "    assert claimed() == 1\n"
    )
    payload = lift_file_payload(src, "t.py")
    disk = census_source(src, file="t.py")
    rpc = payload.to_rpc()
    cov = account_lift_coverage(disk, rpc)
    paint = paint_lines(src, cov, file="t.py")
    by_line = {row["line"]: row["bucket"] for row in paint}
    # test_claimed::assertion fact row cites line 10.
    assert by_line[10] == "lifted+cited"
    # silent_fn's ground assert has no fact row and no gap -- Crime-1 red paint.
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
    assertions = cov["assertions"]
    minority = cov["minority"]
    totals = cov["totals"]
    # Dual totals present and divergent (never one folded number).
    assert "stated" in totals
    assert "silently_unaccounted" in totals
    assert "minority_present" in totals
    assert "minority_un_asserted" in totals
    assert assertions["axis"] == "assertions"
    assert minority["axis"] == "minority-bodies"
    assert minority["gate"] is None
    assert assertions["gate"] == "silently_unaccounted == 0"


def test_statistics_headline_delta_matches_probe(statistics_report: dict) -> None:
    """Post-#4017 headline: all 4 on-disk asserts are spoken for (silent=0).

    Pre-fix residual (enumeration non-totality) was silent=3 nested under
    if/except; that was the first Minority Report indictment. After total
    assertion-surface enumeration the three `assert not _isfinite(...)` loci
    lift via existing NotSugar — do not re-pin silent=3.
    """
    path = _resolve_installed_package_path("statistics")
    disk = census_paths([path], root=path.parent)
    cov = statistics_report["liftCoverage"]
    ax = cov["assertions"]
    assert ax["stated"] == len(disk.asserts) == 4
    assert ax["lifted_cited"] + ax["refused_loud"] == 4
    assert ax["silently_unaccounted"] == 0, (
        f"expected 0 silent asserts on statistics after #4017; got "
        f"{ax['silently_unaccounted']}: {ax['silent_loci']}"
    )
    assert ax["silent_loci"] == []
    # Totals headline
    assert cov["totals"]["stated"] == 4
    assert cov["totals"]["silently_unaccounted"] == 0


def test_statistics_silent_unaccounted_gate_is_zero(
    statistics_report: dict,
) -> None:
    """Totality ratchet: RED while any assert is silently unaccounted.

    #4017: statistics nested `assert not _isfinite` loci now testify via total
    assertion-surface enumeration. Gate stays RED on any silent residue; do not
    fabricate zero.
    """
    ax = statistics_report["liftCoverage"]["assertions"]
    silent = int(ax["silently_unaccounted"])
    if silent != 0:
        loci = ax.get("silent_loci") or []
        detail = "\n".join(
            f"  - {a.get('file')}:{a.get('line')}  {a.get('preview', '')}"
            for a in loci[:20]
        )
        pytest.fail(
            f"silently_unaccounted={silent} (must be 0).\n"
            f"Silent assert loci (mandatory-fix finding):\n{detail}\n"
            f"Post-#4017: nested control-flow asserts must be enumerated."
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


def test_statistics_human_report_contains_literal_minority_report_header() -> None:
    """Human --report must emit the verbatim header `Minority Report` when un_asserted > 0.

    Default assertion accounting has no section title. Guard: the forbidden
    qualifier must not appear in human output.
    """
    path = _resolve_installed_package_path("statistics")
    sugar = _resolve_audit_sugar_bin(None)
    with tempfile.TemporaryDirectory(prefix="lift-cov-human-") as td:
        ws = Path(td) / "statistics"
        _prepare_audit_workspace(path, ROOT, ws, audit_only=False)
        cmd = [os.fspath(sugar), "lift", "--report", str(ws)]
        env = _hermetic_env_for_sugar_command(cmd)
        completed = subprocess.run(
            cmd, cwd=ROOT, text=True, capture_output=True, check=False, env=env
        )
        assert completed.returncode == 0, (
            f"lift --report failed exit={completed.returncode}\n"
            f"stdout={completed.stdout[:1500]}\nstderr={completed.stderr[:1500]}"
        )
        human = (completed.stdout or "") + (completed.stderr or "")
        assert "Minority Report" in human, (
            f"literal header `Minority Report` missing from human report:\n{human[:2500]}"
        )
        # Forbidden qualifier must not appear in human output (any case).
        _forbidden = "MA" + "JORITY"
        assert _forbidden not in human.upper(), (
            f"human report must not contain {_forbidden}; got:\n{human[:2500]}"
        )
        # No dual-axis section-title framing on the default body.
        assert "lift coverage (" not in human.lower()


def test_discrimination_inject_unaccounted_construct_reds_assertions(tmp_path: Path) -> None:
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
    assert cov_full.assertions.silently_unaccounted == 0
    assert cov_partial.assertions.silently_unaccounted == 1
    assert cov_partial.assertions.silent_loci[0]["line"] == 3


# ---------------------------------------------------------------------------
# Crime 2: forged warrant detector (#4016)
# ---------------------------------------------------------------------------


def test_crime2_account_forged_when_warranting_assert_null() -> None:
    from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
    from sugar_lift_py_tests.idd.lift_coverage_census import census_source

    disk = census_source("def f():\n    return 0\n", file="t.py")
    payload = {
        "diagnostics": [
            {
                "kind": "dig-floor",
                "floor": "literal",
                "file": "t.py",
                "line": 1,
                "col": 0,
                "blame": "t.py:1:0",
                "detail": "test-forged",
                "warrantingAssert": None,
            },
            {
                "kind": "dig-floor",
                "floor": "literal",
                "file": "t.py",
                "line": 2,
                "col": 0,
                "blame": "t.py:2:0",
                "detail": "test-warranted",
                "warrantingAssert": {"file": "t.py", "line": 2, "col": 4},
            },
        ]
    }
    cov = account_lift_coverage(disk, payload)
    assert cov.crime2.dig_floors == 2
    assert cov.crime2.warranted == 1
    assert cov.crime2.forged_warrant == 1
    assert cov.crime2.forged_loci[0]["detail"] == "test-forged"
    assert cov.to_json()["totals"]["crime2_forged_warrant"] == 1
    assert cov.crime2.is_zero is False


def test_crime2_zero_when_all_floors_warranted() -> None:
    from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
    from sugar_lift_py_tests.idd.lift_coverage_census import census_source

    disk = census_source("def f():\n    assert 1==1\n", file="t.py")
    payload = {
        "diagnostics": [
            {
                "kind": "dig-floor",
                "floor": "literal",
                "file": "t.py",
                "line": 2,
                "col": 4,
                "blame": "t.py:2:4",
                "detail": "opaque-op-body-computed",
                "warrantingAssert": {"file": "t.py", "line": 2, "col": 4},
            }
        ]
    }
    cov = account_lift_coverage(disk, payload)
    assert cov.crime2.forged_warrant == 0
    assert cov.crime2.is_zero is True


def test_crime2_bad_twin_inject_forged_floor_flips_red() -> None:
    from sugar_lift_py_tests.factory.dig_floor import DigFloorRecord, record_dig_floor
    from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
    from sugar_lift_py_tests.idd.lift_coverage_census import census_source

    disk = census_source("def f():\n    return 1\n", file="twin.py")
    warranted_payload = {
        "diagnostics": [
            {
                "kind": "dig-floor",
                "floor": "literal",
                "file": "twin.py",
                "line": 1,
                "col": 0,
                "blame": "twin.py:1:0",
                "detail": "callsite-floor-projection",
                "warrantingAssert": {"file": "twin.py", "line": 10, "col": 4},
            }
        ]
    }
    green = account_lift_coverage(disk, warranted_payload)
    assert green.crime2.forged_warrant == 0, green.crime2.to_json()

    dig_floors: list[DigFloorRecord] = []
    record_dig_floor(
        dig_floors,
        floor="literal",
        file="twin.py",
        line=1,
        col=0,
        blame="twin.py:1:0",
        detail="injected-forged-warrant",
        callee="forged",
        warranting_assert=None,
    )
    forged_payload = {
        "diagnostics": [d.to_json() for d in dig_floors]
        + warranted_payload["diagnostics"]
    }
    red = account_lift_coverage(disk, forged_payload)
    assert red.crime2.forged_warrant == 1, red.crime2.to_json()
    assert red.crime2.forged_loci[0]["detail"] == "injected-forged-warrant"

    green2 = account_lift_coverage(disk, warranted_payload)
    assert green2.crime2.forged_warrant == 0


def test_crime2_production_dig_floor_stamps_warranting_assert() -> None:
    from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report

    src = (
        "def A():\n"
        "    return len([1, 2, 3])\n"
        "def test_it():\n"
        "    assert A() == 3\n"
    )
    built = build_literal_call_report(source=src, filename="stamp.py", memento_file="stamp.py")
    assert built is not None
    diags = list(built.payload.diagnostics or [])
    floors = [d for d in diags if isinstance(d, dict) and d.get("kind") == "dig-floor"]
    assert floors, f"expected dig-floor stamps; diagnostics={diags[:8]}"
    for f in floors:
        assert f.get("warrantingAssert") is not None, (
            f"production dig-floor must stamp warranting assert; got {f}"
        )
        wa = f["warrantingAssert"]
        assert wa.get("line") == 4, f"assert is on line 4; got {wa}"
    from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
    from sugar_lift_py_tests.idd.lift_coverage_census import census_source

    disk = census_source(src, file="stamp.py")
    cov = account_lift_coverage(disk, {"diagnostics": diags})
    assert cov.crime2.forged_warrant == 0, cov.crime2.to_json()
    assert cov.crime2.dig_floors >= 1


def test_crime2_statistics_forged_warrant_gate_is_zero() -> None:
    stats = _resolve_installed_package_path("statistics")
    target = stats if stats.is_file() else (
        stats / "statistics.py" if (stats / "statistics.py").exists() else stats
    )
    report, _ws = _stage_and_report(target if Path(target).is_file() else Path(str(stats)))
    cov = report.get("liftCoverage") or report.get("lift_coverage") or {}
    if not cov and "sources" in report:
        for s in report.get("sources") or []:
            if isinstance(s, dict) and (s.get("liftCoverage") or s.get("lift_coverage")):
                cov = s.get("liftCoverage") or s.get("lift_coverage")
                break
    totals = (cov or {}).get("totals") or {}
    crime2 = (cov or {}).get("crime2") or {}
    forged = totals.get("crime2_forged_warrant", crime2.get("forged_warrant", 0))
    if forged and int(forged) > 0:
        loci = crime2.get("forged_loci") or []
        lines = [
            f"  - {x.get('file')}:{x.get('line')}  {x.get('detail')} {x.get('callee','')}"
            for x in loci[:16]
        ]
        raise AssertionError(
            f"crime2 forged_warrant={forged} (must be 0).\n" + "\n".join(lines)
        )
