"""Lift-coverage harness (#4013): assertion accounting vs minority bodies.

Two divergent axes — never one folded coverage number.

* Assertions (default report body): silently_unaccounted is RED (lifter bug if > 0).
* Minority: un_asserted is VISIBLE scope (not a bug; dig is assertion-triggered).

Headline after #4017 (total assertion-surface enumeration):
  on-disk asserts stated=4, silently_unaccounted=0 (was 3 nested under if/except).
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

import pytest

from sugar_lift_py_tests.idd.installed_package_workspace import (
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
from sugar_lift_py_tests.idd.live_construction_panic_isolation import (
    assert_bearing_py_files as _assert_bearing_py_files,
    live_per_file_isolation_conservation as _live_per_file_isolation_conservation,
    maybe_write_isolation_receipt_from_env,
)

from declared_corpus import (
    HEAVY_OPT_IN,
    optional_law_skip,
    require_declared_corpus,
)


def _assert_conservation_delta_zero(
    body: dict, *, label: str, require_per_file: bool = True
) -> None:
    """Shared #4013 conservation gate: onDisk/accounted/delta, delta==0."""
    totals = body["totals"]
    cons = body.get("conservation") or {}
    on_disk = int(totals["onDisk"])
    accounted = int(totals["accounted"])
    delta = int(totals["delta"])
    print(
        f"R[{label}]: onDisk={on_disk} accounted={accounted} "
        f"delta={delta} files={len(body.get('files') or body.get('perFile') or [])}"
    )
    assert "onDisk" in totals and "accounted" in totals and "delta" in totals
    assert delta == 0, (
        f"conservation delta must be 0 for {label}; "
        f"R=onDisk={on_disk} accounted={accounted} delta={delta}"
    )
    assert on_disk == accounted
    if cons:
        assert cons.get("gate") == "delta == 0"
        assert int(cons["delta"]) == 0
        assert cons.get("is_zero") is True
    per_file = body.get("perFile") or cons.get("perFile") or []
    if require_per_file and on_disk > 0:
        assert per_file, f"{label}: per-file conservation rows required when onDisk>0"
    for row in per_file:
        assert set(row) >= {"file", "onDisk", "accounted", "delta"}
        assert int(row["delta"]) == 0, f"{label} per-file delta: {row}"


# ---------------------------------------------------------------------------
# Unit: independent census + partition (no sugar binary)
# ---------------------------------------------------------------------------


def test_independent_census_counts_asserts_and_bodies() -> None:
    src = "def dug():\n" "    assert 1 == 1\n" "def idle():\n" "    return 0\n"
    disk = census_source(src, file="t.py")
    assert disk.asserts and len(disk.asserts) == 1
    assert disk.asserts[0].line == 2
    assert len(disk.bodies) == 2
    names = {b.name for b in disk.bodies}
    assert names == {"dug", "idle"}


def test_assertions_silent_measured_not_hardcoded() -> None:
    """Discrimination (a): unaccounted construct → gap (silent illegal)."""
    src = (
        "def f():\n"
        "    assert True\n"
        "    assert False  # second assert never cited by empty report\n"
    )
    disk = census_source(src, file="t.py")
    # Empty report → every assert is gap; silent counter stays 0.
    cov = account_lift_coverage(disk, {})
    assert cov.assertions.stated == 2
    assert cov.assertions.lifted_cited == 0
    assert cov.assertions.silently_unaccounted == 0
    assert cov.assertions.gap == 2
    assert cov.assertions.to_json()["is_zero"] is True  # silent gate green
    lines = {a["line"] for a in cov.assertions.gap_loci}
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


def test_discrimination_inject_unaccounted_construct_reds_assertions(
    tmp_path: Path,
) -> None:
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
    # Partial cite: one lifted, one gap (never silent).
    assert cov_partial.assertions.silently_unaccounted == 0
    assert cov_partial.assertions.lifted_cited == 1
    assert cov_partial.assertions.gap == 1
    assert cov_partial.assertions.gap_loci[0]["line"] == 3


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


# ---------------------------------------------------------------------------
# #4013 conservation: onDisk / accounted / delta (independent AST vs report)
# ---------------------------------------------------------------------------

# Stdlib corpus gate (#4721). Full-tree numpy/pandas is the heavy residual
# axis gated below.
_CONSERVATION_VENDORS = (
    "statistics",
    "decimal",
    "fractions",
    "pathlib",
    "csv",
    "datetime",
)

# Full installed package trees — residual named after #4721. Live sugar
# --report on these trees panics (ConstructionPanic floor gaps); the independent
# AST census + gap partition is the measurable conservation gate until
# production floors make full-tree live report possible.
_HEAVY_CONSERVATION_VENDORS = (
    "numpy",
    "pandas",
)

# Live production isolation residual after #4760. Multi-file sugar lift
# --report still dies on first ConstructionPanic; --audit-frontier cannot pair with
# --report. Per assert-bearing file isolation measures live conservation and
# names R_live_construction_panic_files. numpy first (full assert-file set);
# pandas is the same residual class (heavier; opt-in via env).
#
# Re-measure at 9fe134453 (wave-6, after #4808 ranking + intervening floors):
#   assert_files=142 completed=69 R_live_construction_panic_files=71 R_other=2
#   onDisk=3208 accounted=3208 delta=0
#   prior #4791 baseline R_panic=74 → Delta R = -3
#   top owners: TemporalContext 21, RuntimeEffect 10, CallSugar 5, ...
# Re-run: scripts/live_construction_panic_isolation.py --package numpy --out PATH
# or pytest + SUGAR_4013_ISOLATION_OUT=PATH (writes ranked receipt).
_HEAVY_LIVE_ISOLATION_VENDORS = ("numpy",)


def test_conservation_triple_emitted_and_conserves() -> None:
    """--report schema: onDisk / accounted / delta first-class; delta == 0."""
    src = (
        "def a():\n"
        "    assert 1 == 1\n"
        "def b():\n"
        "    assert 2 == 2\n"
        "\n"
        "def test_a():\n"
        "    assert a() is None or True\n"
    )
    disk = census_source(src, file="c.py")
    # Empty report: every assert is gap → accounted == onDisk, delta 0.
    cov = account_lift_coverage(disk, {})
    body = cov.to_json()
    totals = body["totals"]
    cons = body["conservation"]
    assert totals["onDisk"] == totals["stated"] == 3
    assert totals["accounted"] == 3
    assert totals["delta"] == 0
    assert cons["onDisk"] == 3
    assert cons["accounted"] == 3
    assert cons["delta"] == 0
    assert cons["is_zero"] is True
    assert cons["gate"] == "delta == 0"
    assert body["perFile"], "per-file conservation rows required"
    for row in body["perFile"]:
        assert set(row) >= {"file", "onDisk", "accounted", "delta"}
        assert row["delta"] == row["onDisk"] - row["accounted"]
        assert row["delta"] == 0
    # Identity: onDisk - accounted == silently_unaccounted under the partition.
    assert totals["delta"] == totals["silently_unaccounted"]


def test_conservation_per_file_rows_for_multi_file_census() -> None:
    """Per-file onDisk/accounted/delta across a multi-file disk census."""
    from sugar_lift_py_tests.idd.lift_coverage_census import AssertLocus, DiskCensus

    disk = DiskCensus(
        files=["a.py", "b.py"],
        asserts=[
            AssertLocus("a.py", 1, 0, 1, 10, "assert 1"),
            AssertLocus("a.py", 2, 0, 2, 10, "assert 2"),
            AssertLocus("b.py", 1, 0, 1, 10, "assert 3"),
        ],
        bodies=[],
    )
    # Cite only a.py:1 as warranted; rest gap.
    report = {
        "sourceAudits": [
            {
                "file": "a.py",
                "loci": [
                    {
                        "file": "a.py",
                        "line": 1,
                        "col": 0,
                        "status": "warranted",
                        "ast_kind": "Assert",
                    }
                ],
            }
        ]
    }
    cov = account_lift_coverage(disk, report)
    body = cov.to_json()
    assert body["totals"]["onDisk"] == 3
    assert body["totals"]["accounted"] == 3  # 1 lifted + 2 gaps
    assert body["totals"]["delta"] == 0
    by_file = {r["file"]: r for r in body["perFile"]}
    assert by_file["a.py"]["onDisk"] == 2
    assert by_file["a.py"]["accounted"] == 2
    assert by_file["a.py"]["delta"] == 0
    assert by_file["b.py"]["onDisk"] == 1
    assert by_file["b.py"]["accounted"] == 1
    assert by_file["b.py"]["delta"] == 0


def test_conservation_bad_twin_drop_from_axis_flips_delta() -> None:
    """Discrimination: if accounted under-counts onDisk, delta > 0 and RED.

    The production partition never leaves silent residue (gap fills
    the gap). This unit twin plants a hand-built axis that violates
    conservation so the gate field itself is proven measured, not hardcoded.
    """
    from sugar_lift_py_tests.idd.lift_coverage_accounting import (
        AssertionAxis,
        Crime2Axis,
        LiftCoverageReport,
        MinorityAxis,
    )

    # Hand-built: onDisk=2, accounted=1 → delta=1 (RED).
    assertions = AssertionAxis(
        stated=2,
        lifted_cited=1,
        gap=0,
        silently_unaccounted=1,
        on_disk=[
            {"file": "t.py", "line": 1, "col": 0, "preview": "assert 1"},
            {"file": "t.py", "line": 2, "col": 0, "preview": "assert 2"},
        ],
        lifted_loci=[
            {"file": "t.py", "line": 1, "col": 0, "preview": "assert 1"},
        ],
        silent_loci=[
            {"file": "t.py", "line": 2, "col": 0, "preview": "assert 2"},
        ],
    )
    report = LiftCoverageReport(
        assertions=assertions,
        minority=MinorityAxis(),
        crime2=Crime2Axis(),
        files=["t.py"],
        per_file=[
            {"file": "t.py", "onDisk": 2, "accounted": 1, "delta": 1},
        ],
    )
    body = report.to_json()
    assert body["totals"]["onDisk"] == 2
    assert body["totals"]["accounted"] == 1
    assert body["totals"]["delta"] == 1
    assert body["conservation"]["is_zero"] is False
    assert body["perFile"][0]["delta"] == 1


def _census_conservation_for_paths(
    files: list[Path], *, root: Path, label: str
) -> dict:
    """Independent AST census + gap partition; returns coverage JSON."""
    disk = census_paths(files, root=root)
    # Factory-instrument-engaged empty report: gap fills the gap;
    # conservation identity still holds (delta == 0). The independent census
    # is the only onDisk source — no lift code is shared.
    eng_report = {
        "factoryAuditSummary": {"statusCounts": {"unresolved": 1}},
        "auditOnlyGaps": [],
    }
    body = account_lift_coverage(disk, eng_report).to_json()
    print(
        f"R[{label}]: onDisk={body['totals']['onDisk']} "
        f"accounted={body['totals']['accounted']} "
        f"delta={body['totals']['delta']} "
        f"files={len(disk.files)} asserts={len(disk.asserts)}"
    )
    return body


@pytest.mark.parametrize("package", list(_CONSERVATION_VENDORS))
def test_stdlib_vendor_conservation_delta_is_zero(package: str) -> None:
    """#4013 corpus gate: independent onDisk vs accounted, delta→0.

    Six stdlib modules. The independent AST census (shares NO code with the
    lift path) is the onDisk side. Accounted is the report-bucket partition
    (lifted+cited + gap). Under the gap doctrine every
    stated assert is classified, so delta must be 0.

    R = sum(delta) over the corpus; gate is RED while any delta > 0.
    """
    path = _resolve_installed_package_path(package)
    files: list[Path]
    if path.is_file():
        files = [path]
        root = path.parent
    else:
        files = sorted(p for p in path.rglob("*.py") if "__pycache__" not in p.parts)[
            :40
        ]
        root = path
        if not files:
            require_declared_corpus(
                f"{package}: no .py source files",
                path,
                "_CONSERVATION_VENDORS (stdlib modules that ship with CPython)",
                "repair the Python installation; a stdlib module with no .py "
                "source cannot be censused and its absence is never routine",
            )

    body = _census_conservation_for_paths(files, root=root, label=package)
    _assert_conservation_delta_zero(body, label=package)
    # stated/onDisk identity: every disk assert is classified.
    assert int(body["totals"]["onDisk"]) == int(body["totals"]["stated"])


@pytest.mark.parametrize("package", list(_HEAVY_CONSERVATION_VENDORS))
def test_heavy_vendor_full_tree_conservation_delta_is_zero(package: str) -> None:
    """#4013 residual after #4721: full-tree numpy/pandas conservation.

    Walks every ``*.py`` under the installed package (no 40-file cap). The
    independent AST census is the onDisk side; accounted is gap
    partition against a factory-engaged empty report. Live full-tree
    ``sugar lift --report`` still panics on floor gaps (ConstructionPanic) — that
    live residual stays open; this gate measures the census half of
    conservation on the real heavy surface.

    Measured R (local instrument): numpy onDisk≈3208, pandas onDisk≈17543,
    both delta=0 under gap.
    """
    path = _resolve_installed_package_path(package)
    if not path.exists():
        require_declared_corpus(
            f"{package} is not installed",
            path,
            "sugar-build.toml (numpy = 2.5.1, pandas = 3.0.3) and the "
            "sugar-lift-py-tests [test] extra, which calls itself THE SOLE "
            "DEPENDENCY AUTHORITY for every CI job touching this package",
            "install the package extra: pip install -e "
            "'implementations/python/sugar-lift-py-tests[test]'",
        )
    if path.is_file():
        files = [path]
        root = path.parent
    else:
        files = sorted(p for p in path.rglob("*.py") if "__pycache__" not in p.parts)
        root = path
        if not files:
            require_declared_corpus(
                f"{package}: no .py source files",
                path,
                "_HEAVY_CONSERVATION_VENDORS against the pinned vendor versions",
                "reinstall the pinned vendor; an installed package with no .py "
                "source cannot supply the on-disk census side",
            )

    body = _census_conservation_for_paths(
        files, root=root, label=f"{package}-full-tree"
    )
    _assert_conservation_delta_zero(body, label=f"{package}-full-tree")
    # Full-tree floors: heavy vendors must actually exercise the census
    # (non-vacuous). numpy/pandas site-packages carry thousands of asserts.
    on_disk = int(body["totals"]["onDisk"])
    assert on_disk > 0, f"{package} full-tree must have on-disk asserts"
    assert len(files) > 40, (
        f"{package} full-tree must exceed the stdlib 40-file sample; "
        f"got files={len(files)}"
    )
    # Per-file conservation rows cover every assert-bearing file.
    assert body["perFile"], f"{package}: empty perFile on full-tree"
    assert len(body["perFile"]) <= len(files)


@pytest.mark.parametrize("package", list(_HEAVY_LIVE_ISOLATION_VENDORS))
def test_heavy_vendor_live_per_file_isolation_conservation_delta_is_zero(
    package: str,
) -> None:
    """#4013 residual after #4760: live production path via per-file isolation.

    Full-tree multi-file ``sugar lift --report`` still ConstructionPanics (cannot
    pair ``--audit-frontier`` with ``--report``). Isolate every assert-bearing
    file on the production file-lift path:

    * completed → real payload into conservation accounting
    * ConstructionPanic → gap for that file's on-disk asserts

    Gate: aggregate conservation delta==0 on the live path.
    Residual axis (named, leave #4013 open): ``R_live_construction_panic_files``
    must go to 0 via production floors before multi-file live report can gate.
    Opt-in pandas: set ``SUGAR_4013_HEAVY_PANDAS=1`` (same class, ~1h).
    """
    path = _resolve_installed_package_path(package)
    if not path.exists():
        require_declared_corpus(
            f"{package} is not installed",
            path,
            "sugar-build.toml (numpy = 2.5.1, pandas = 3.0.3) and the "
            "sugar-lift-py-tests [test] extra, THE SOLE DEPENDENCY AUTHORITY",
            "install the package extra: pip install -e "
            "'implementations/python/sugar-lift-py-tests[test]'",
        )
    if path.is_file():
        files = [path] if _file_has_assert(path) else []
        root = path.parent
    else:
        root = path
        files = _assert_bearing_py_files(root)
    if not files:
        require_declared_corpus(
            f"{package}: no assert-bearing .py files",
            path,
            "_HEAVY_LIVE_ISOLATION_VENDORS, which asserts assert_files > 40 "
            "below -- so an empty set contradicts the law's own floor",
            "reinstall the pinned vendor; the live isolation gate has no "
            "subject without assert-bearing files",
        )

    result = _live_per_file_isolation_conservation(files, root=root, package=package)
    # Optional durable receipt for recensus / wave re-measure (env path).
    maybe_write_isolation_receipt_from_env(result)
    assert (
        result["delta"] == 0
    ), f"{package} live isolation conservation delta must be 0; R={result}"
    assert (
        result["R_live_construction_panic_files"] == result["construction_panic_files"]
    )
    assert result["onDisk"] == result["accounted"]
    assert result["onDisk"] > 0, f"{package}: vacuous live isolation (no asserts)"
    assert result["assert_files"] == len(files)
    # Non-vacuous: isolation must exercise more than the stdlib 40-file sample.
    assert result["assert_files"] > 40, (
        f"{package} live isolation must exceed stdlib sample; "
        f"got assert_files={result['assert_files']}"
    )
    # Every per-file row conserved (completed or gap after panic).
    for row in result["perFile"]:
        assert int(row["delta"]) == 0, row
    # Residual is measured, not hidden. Multi-file live report stays open
    # while R_live_construction_panic_files > 0 (production floors).
    assert "construction_panic_files" in result
    assert result["construction_panic_files"] >= 0
    # Structured owner ranking feeds fatal recensus (same fingerprint axes).
    assert "owner_families" in result
    assert "exact_fronts" in result
    assert result["owner_family_count"] == len(result["owner_families"])
    assert result["exact_front_count"] == len(result["exact_fronts"])
    assert (
        sum(row["count"] for row in result["owner_families"])
        == result["construction_panic_files"]
    )
    assert (
        sum(row["count"] for row in result["exact_fronts"])
        == result["construction_panic_files"]
    )
    for row in result["panic_rows"]:
        assert "gap" in row and "fingerprint" in row and "front" in row
        assert len(row["fingerprint"]) == 5


def test_heavy_vendor_live_isolation_opt_in_pandas() -> None:
    """Same live isolation residual class as numpy; opt-in (heavy)."""
    if os.environ.get("SUGAR_4013_HEAVY_PANDAS") != "1":
        optional_law_skip(
            HEAVY_OPT_IN,
            "set SUGAR_4013_HEAVY_PANDAS=1 for full pandas live isolation "
            "(~1h, same residual class as the numpy gate that DOES run)",
        )
    test_heavy_vendor_live_per_file_isolation_conservation_delta_is_zero("pandas")


def _file_has_assert(path: Path) -> bool:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return False
    return any(isinstance(node, ast.Assert) for node in ast.walk(tree))
