"""Criterion 14 conservation ratchet tests.

Part of #3686 / #3706. Pins the exact, honestly-measured residue
R(unaccounted-lines-over-itsdangerous) for a small real itsdangerous slice
(url_safe.py's base64 helpers, tests/fixtures/criterion14/) against the
report shape `sugar lift --report --json` emits
(implementations/rust/sugar-cli/src/report_fmt.rs +
implementations/rust/sugar-cli/src/line_accounting.rs).

As of #3706 the report grew a `lineAccounting` array: warrant (a discharged
row with a followable CID) and effect (a refused row: callee names the
effect, `reason` is the grounds) come from callsite rows alone; support (an
affirmatively inert line: blank, import, docstring, bare def/class
signature) is layered on top by `cmd_lift::render_report_json`, which has
source-file access `report_fmt` does not.

R is NOT zero on this slice, and this test does not pretend otherwise: the
support classifier is deliberately narrow (blank/import/docstring/signature
only). Ordinary statement lines inside a warranted function body -- the
`if isinstance(...)`/`.encode(...)` lines, and the `raise` line whose
refused-effect row is anchored one line up at the `except:` line -- are not
support and are not separately warranted, so they stay honest residue. That
residue count is the campaign meter: it should shrink only as real
classification coverage lands (e.g. body lines under an already-discharged
function's CID becoming warrant too), never by relaxing this test.
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

RESIDUE_LINES = frozenset({15, 16, 25, 26, 27, 28, 31})
SUPPORT_LINES = frozenset(
    {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 18, 19, 20, 21, 22, 23, 24}
)


@pytest.fixture(scope="module")
def report_json():
    return json.loads(REPORT.read_text())


def test_warrant_lines_are_the_discharged_cid_bearing_rows(report_json):
    result = check_conservation(report_json, SOURCE)
    assert result.warrant_lines == frozenset({17, 29})
    assert result.warrant == 2


def test_refused_row_is_now_an_effect_line(report_json):
    result = check_conservation(report_json, SOURCE)
    # Line 30 (the refused Exception row) is now classified `effect`: the
    # row's callee names the effect, its `reason` is the grounds. It must
    # NOT show up in the residue any more.
    assert result.effect_lines == frozenset({30})
    assert result.effect == 1
    assert not any(r.line == 30 for r in result.unaccounted)


def test_support_lines_cover_blanks_imports_docstrings_and_signatures(report_json):
    result = check_conservation(report_json, SOURCE)
    assert result.support_lines == SUPPORT_LINES
    assert result.support == len(SUPPORT_LINES)


def test_ordinary_statement_lines_stay_honest_residue(report_json):
    result = check_conservation(report_json, SOURCE)
    # The `if isinstance(...)`/`.encode(...)` body lines are neither
    # support (they are not inert) nor separately warranted (no row anchors
    # a CID to them); they must remain unaccounted, not be invented as
    # support just to shrink the number.
    residue_lines = {r.line for r in result.unaccounted}
    assert residue_lines == RESIDUE_LINES


def test_measured_conservation_residue_pinned_baseline(report_json):
    """R(unaccounted-lines-over-itsdangerous) baseline for this slice.

    Measured after #3706: 31 total lines, 2 warrant, 21 support, 1 effect ->
    7 unaccounted (down from the pre-#3706 baseline of 29). This is the
    honest pin (T's law: never fake a zero). Ratchet direction is downward
    only: a future PR may lower this number by growing real classification
    coverage in the report schema or lift pipeline, or by widening the
    fixture; it must never raise it silently.
    """
    result = check_conservation(report_json, SOURCE)
    assert result.total_lines == 31
    assert result.warrant == 2
    assert result.support == 21
    assert result.effect == 1
    assert result.residue == 7
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
    assert "R(unaccounted-lines-over-itsdangerous_url_safe_slice.py) = 7" in captured.err
    assert "UNACCOUNTED itsdangerous_url_safe_slice.py:15" in captured.err


def test_cli_max_residue_escape_hatch_permits_pinned_baseline(capsys):
    from criterion14_conservation import main

    exit_code = main([str(REPORT), str(SOURCE), "--max-residue", "7"])
    assert exit_code == 0
