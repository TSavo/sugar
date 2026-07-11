# SPDX-License-Identifier: MIT OR Apache-2.0
"""Ratchets for Download sources (#4106/#4107) + diggable lift (item 1+2).

1) After sdist download, on-disk census **stated asserts ≫ 0** (itsdangerous).
2) A diggable claim against the vendor package **lifts** (not silent) when the
   package is importable — proves the path can add speaking assertion lines,
   not only dark stated mass.

Real pytest suites (parametrize / isinstance) remain mostly silent until the
factory speaks those shapes; that is tracked as remaining #4106 work, not
hidden green.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_paths, census_source
from sugar_lift_py_tests.lift_rpc import lift_file_payload

REPO = Path(__file__).resolve().parents[4]
SCRIPT = (
    REPO
    / "implementations/rust/sugar-lsp/scripts/download_package_sources.py"
)


def _python() -> str:
    return os.environ.get("PYTHON") or sys.executable


@pytest.fixture(scope="module")
def itsdangerous_sdist_root(tmp_path_factory) -> Path:
    pytest.importorskip("itsdangerous")
    if not SCRIPT.is_file():
        pytest.skip(f"missing {SCRIPT}")
    cache = tmp_path_factory.mktemp("sugar-sources")
    out = subprocess.check_output(
        [_python(), str(SCRIPT), "itsdangerous", str(cache)],
        text=True,
        timeout=180,
    )
    data = json.loads(out)
    assert data.get("ok"), data
    root = Path(data["root"])
    assert root.is_dir()
    assert (root / "tests").is_dir(), "sdist must include tests/"
    return root


def test_download_sources_stated_assert_count_ratchet(itsdangerous_sdist_root: Path) -> None:
    """Item 1: claim surface appears after Download sources (0 on wheel → ≫0 on sdist)."""
    files = sorted(
        p
        for p in itsdangerous_sdist_root.rglob("*.py")
        if "__pycache__" not in p.parts
    )
    disk = census_paths(files, root=itsdangerous_sdist_root)
    # Wheel-only itsdangerous had 0 asserts; sdist+tests must clear a real floor.
    assert len(disk.asserts) >= 50, (
        f"expected ≥50 on-disk asserts after sdist download; got {len(disk.asserts)}"
    )
    assert len(disk.bodies) >= 80


def test_diggable_vendor_assert_lifts_not_silent() -> None:
    """Item 2: diggable claim against itsdangerous **lifts** (lifted_cited ≥ 1).

    Uses a diggable shape the membrane already handles (call == literal),
    importing from the installed/diggable package — same class as sdist tests
    once shapes are supported.
    """
    pytest.importorskip("itsdangerous")
    src = (
        "from itsdangerous.encoding import int_to_bytes, bytes_to_int\n"
        "\n"
        "def test_int_roundtrip():\n"
        "    assert bytes_to_int(int_to_bytes(192)) == 192\n"
    )
    rpc = lift_file_payload(src, "diggable_itsdangerous.py").to_rpc()
    disk = census_source(src, file="diggable_itsdangerous.py")
    cov = account_lift_coverage(disk, rpc)
    ax = cov.to_json()["assertions"]
    assert ax["stated"] == 1
    assert ax["lifted_cited"] >= 1, (
        f"diggable itsdangerous assert must lift; got {ax}"
    )
    assert ax["silently_unaccounted"] == 0


def test_download_tree_still_mostly_silent_on_raw_pytest_suite(
    itsdangerous_sdist_root: Path,
) -> None:
    """Honesty ratchet: raw sdist tests are stated but largely silent today.

    Prevents claiming 'download fixed Crime 1' when only census grew.
    """
    test_files = sorted((itsdangerous_sdist_root / "tests").rglob("*.py"))
    stated = lifted = silent = 0
    for p in test_files:
        src = p.read_text(encoding="utf-8", errors="replace")
        rpc = lift_file_payload(src, str(p)).to_rpc()
        cov = account_lift_coverage(census_source(src, file=str(p)), rpc)
        a = cov.to_json()["assertions"]
        stated += a["stated"]
        lifted += a["lifted_cited"]
        silent += a["silently_unaccounted"]
    assert stated >= 50
    # Document current membrane: pytest/parametrize/isinstance remain silent.
    assert silent + lifted == stated
    assert silent >= 40, "if this drops a lot, update the honesty note + gallery"
