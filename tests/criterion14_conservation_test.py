"""Criterion 14 conservation ratchet tests.

Part of #3686. Pins the exact, honestly-measured residue
R(unaccounted-lines-over-itsdangerous) for a small real itsdangerous slice
(url_safe.py's base64 helpers, tests/fixtures/criterion14/) against the
report shape `sugar lift --report --json` emits today
(implementations/rust/sugar-cli/src/report_fmt.rs).

R is NOT zero today, and this test does not pretend otherwise: the report
schema only expresses "warrant" (a discharged row with a followable CID).
There is no field for "support" or "effect" yet, so every line the fixture
report does not name as a discharged, CID-bearing row is unaccounted --
including the docstrings, blank lines, the `def` lines, and even the
`refused` Exception row (refused is not a terminal state Criterion 14
recognizes; only warrant/support/effect are). That residue count is the
campaign meter: it should shrink only as real support/effect classification
lands in the report schema, never by relaxing this test.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "tools"))

from criterion14_conservation import check_conservation  # noqa: E402

FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "criterion14"
SOURCE = FIXTURE_DIR / "itsdangerous_url_safe_slice.py"
REPORT = FIXTURE_DIR / "itsdangerous_url_safe_slice.report.json"


@pytest.fixture(scope="module")
def report_json():
    return json.loads(REPORT.read_text())


def test_warrant_lines_are_the_discharged_cid_bearing_rows(report_json):
    result = check_conservation(report_json, SOURCE)
    assert result.warrant_lines == frozenset({17, 29})
    assert result.warrant == 2


def test_report_schema_cannot_express_support_or_effect_today(report_json):
    result = check_conservation(report_json, SOURCE)
    # Honest measurement, not a design choice: today's report_to_json has no
    # field a "support" or "effect" classification could live in. When
    # implementations/rust/sugar-cli/src/report_fmt.rs grows one, this
    # assertion is exactly what should start failing.
    assert result.support == 0
    assert result.effect == 0


def test_refused_row_does_not_count_as_accounted(report_json):
    result = check_conservation(report_json, SOURCE)
    # Line 30 (the refused Exception row) is neither warrant, support, nor
    # effect -- Criterion 14 recognizes exactly three terminal states, and
    # "refused" is not one of them. It must show up in the residue.
    assert any(r.line == 30 for r in result.unaccounted)


def test_measured_conservation_residue_pinned_baseline(report_json):
    """R(unaccounted-lines-over-itsdangerous) baseline for this slice.

    Measured today: 31 total lines, 2 warrant, 0 support, 0 effect -> 29
    unaccounted. This is the honest pin (T's law: never fake a zero). Ratchet
    direction is downward only: a future PR may lower this number by growing
    real support/effect classification in the report schema, or by widening
    the fixture; it must never raise it silently.
    """
    result = check_conservation(report_json, SOURCE)
    assert result.total_lines == 31
    assert result.warrant == 2
    assert result.support == 0
    assert result.effect == 0
    assert result.residue == 29
    assert not result.conserved()


def test_conservation_law_sum_identity(report_json):
    """warrant + support + effect + residue must always equal total_lines.

    This is the accounting identity itself, independent of what the
    schema can currently express: no line may be double-counted or dropped
    by the checker.
    """
    result = check_conservation(report_json, SOURCE)
    assert result.warrant + result.support + result.effect + result.residue == result.total_lines


def test_cli_exits_nonzero_naming_offenders(capsys):
    from criterion14_conservation import main

    exit_code = main([str(REPORT), str(SOURCE)])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "R(unaccounted-lines-over-itsdangerous_url_safe_slice.py) = 29" in captured.err
    assert "UNACCOUNTED itsdangerous_url_safe_slice.py:1" in captured.err


def test_cli_max_residue_escape_hatch_permits_pinned_baseline(capsys):
    from criterion14_conservation import main

    exit_code = main([str(REPORT), str(SOURCE), "--max-residue", "29"])
    assert exit_code == 0
