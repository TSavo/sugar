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

Residue drain (#3706 follow-up, T, 2026-07-06): R is now 0 on this slice.
Two real fixes landed, not a relaxed checker:

1. The `raise Exception(...)` row's callsite now anchors at its own line
   (31), not the `except:` line one up (30) -- matching what the real
   Python lifter already does (`runtime_failure_locus` uses the raise
   AST node's own `lineno`; the prior fixture hand-shaping had drifted from
   that and anchored the row a line early).
2. `line_accounting::expand_body_span_line_accounting` (#3706 follow-up)
   lets a warrant/effect row claim its function's full body span IFF it
   genuinely covers that span: within one function body, each existing
   warrant/effect anchor, in ascending line order, claims every still-
   unclaimed line strictly between the previous anchor (or the function's
   first body line) and itself, under the anchor's own class and grounds.
   Those in-between lines (`if isinstance(...)`, `.encode(...)`, the
   `try:`/accumulation statements) are ordinary straight-line statements
   that must execute on every path that reaches the anchor callsite -- they
   are covered by the exact same proof or refusal the anchor already
   carries, not a new one invented for them. A function with zero rows
   still gets zero expansion (the honesty rule holds): this only ever
   fills gaps between real anchors, never invents coverage past the last
   one.
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

WARRANT_LINES = frozenset({15, 16, 17, 25, 26, 27, 28, 29})
EFFECT_LINES = frozenset({30, 31})
SUPPORT_LINES = frozenset(
    {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 18, 19, 20, 21, 22, 23, 24}
)


@pytest.fixture(scope="module")
def report_json():
    return json.loads(REPORT.read_text())


def test_warrant_lines_are_the_discharged_cid_bearing_rows(report_json):
    result = check_conservation(report_json, SOURCE)
    # 17 and 29 are the original discharged callsite rows; 15/16 and
    # 25/26/27/28 are the body-span expansion of those same two rows (they
    # share the anchor's own CID, per `expand_body_span_line_accounting`).
    assert result.warrant_lines == WARRANT_LINES
    assert result.warrant == 8


def test_refused_row_is_now_an_effect_line(report_json):
    result = check_conservation(report_json, SOURCE)
    # Line 31 (the `raise` itself, now the row's own anchor) and line 30
    # (the `except:` line, backfilled by body-span expansion from the same
    # refused row) are both classified `effect`. Neither shows up in the
    # residue any more.
    assert result.effect_lines == EFFECT_LINES
    assert result.effect == 2
    assert not any(r.line in EFFECT_LINES for r in result.unaccounted)


def test_support_lines_cover_blanks_imports_docstrings_and_signatures(report_json):
    result = check_conservation(report_json, SOURCE)
    assert result.support_lines == SUPPORT_LINES
    assert result.support == len(SUPPORT_LINES)


def test_no_lines_left_as_honest_residue(report_json):
    result = check_conservation(report_json, SOURCE)
    # The former residue lines (the `if isinstance(...)`/`.encode(...)` body
    # statements and the `raise` line) are now genuinely covered: each is a
    # straight-line statement between the function's start and the
    # warrant/effect row anchored at the end of that same straight-line run,
    # sharing that row's own CID/grounds -- not an invented support label.
    residue_lines = {r.line for r in result.unaccounted}
    assert residue_lines == frozenset()


def test_measured_conservation_residue_pinned_baseline(report_json):
    """R(unaccounted-lines-over-itsdangerous) baseline for this slice.

    Measured after the #3706 residue-drain follow-up: 31 total lines, 8
    warrant, 21 support, 2 effect -> 0 unaccounted (down from 7). Two real
    fixes, not a relaxed checker: (1) the raise/except anchor now points at
    the actual `raise` line, matching the real Python lifter's own
    `runtime_failure_locus`, and (2) `expand_body_span_line_accounting` lets
    a warrant/effect row claim its function's full body span when it
    genuinely covers it (contiguous straight-line statements between one
    anchor and the next, sharing the anchor's own CID/grounds). Ratchet
    direction is still downward only: a future PR may add fixture coverage
    that reintroduces named residue elsewhere, but it must never raise this
    baseline silently.
    """
    result = check_conservation(report_json, SOURCE)
    assert result.total_lines == 31
    assert result.warrant == 8
    assert result.support == 21
    assert result.effect == 2
    assert result.residue == 0
    assert result.conserved()


def test_conservation_law_sum_identity(report_json):
    """warrant + support + effect + residue must always equal total_lines.

    This is the accounting identity itself, independent of what the
    schema can currently express: no line may be double-counted or dropped
    by the checker.
    """
    result = check_conservation(report_json, SOURCE)
    assert result.warrant + result.support + result.effect + result.residue == result.total_lines


def test_cli_exits_zero_now_the_slice_is_fully_conserved(capsys):
    from criterion14_conservation import main

    exit_code = main([str(REPORT), str(SOURCE)])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "UNACCOUNTED" not in captured.err
    assert '"residue": 0' in captured.out


def test_cli_max_residue_escape_hatch_still_permits_a_future_regression_budget(capsys):
    from criterion14_conservation import main

    exit_code = main([str(REPORT), str(SOURCE), "--max-residue", "7"])
    assert exit_code == 0
