"""Wall-baselines ratchet: pins the measured per-vendor sourceLedger/failure
shape from the 2026-07-06 battleaxe wall-baselines run (issue #3731, retry
of the orphaned predecessor lane).

These fixtures were produced by `sugar lift --report --json <workspace>`
against real installed packages on battleaxe (numpy 2.5.1, pandas 3.0.3,
itsdangerous 2.2.0, scikit-learn 1.9.0), then distilled to their
`sourceLedger` totals (or, for scikit-learn, the exact loud transport
failure) -- see docs/audits/2026-07-06-criterion14-baselines.md for the
full mechanism writeup and receipts.

This test NEVER re-lifts: it reads the committed distilled JSON only. Full
re-lift is a battleaxe operation (bin/brun), not a CI operation -- CI reads
the pinned artifact and asserts the numbers have not silently drifted.
Loosening any assertion here requires a fresh measured run and an updated
fixture, not a numbers edit.
"""

from __future__ import annotations

import json
from pathlib import Path

FIXTURE_DIR = (
    Path(__file__).resolve().parent
    / "fixtures/criterion14/wall-baselines-2026-07-06"
)


def _load(name: str) -> dict:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def test_numpy_ledger_baseline() -> None:
    data = _load("numpy.ledger-summary.json")
    ledger = data["sourceLedger"]
    # Every audited numpy loci warranted, zero unresolved/unclassified --
    # but note: the directory-wall lift path (cmd_lift.rs:3069) does not
    # emit `lineAccounting`, only `sourceLedger`/`sourceAudits`. That is a
    # real, named gap (not this test's business to paper over): criterion14
    # _conservation.py cannot run against this report shape until the wall
    # path is wired through `line_accounting`, tracked as the retirement
    # path for this row in #3731.
    assert ledger == {
        "source_loci": 1511,
        "source_warranted": 1511,
        "source_support": 0,
        "source_boundary": 0,
        "source_inactive": 0,
        "unclassified_source": 0,
        "source_unresolved": 0,
    }
    assert data["hasLineAccounting"] is False
    assert data["contracts"] == 1526


def test_pandas_ledger_baseline() -> None:
    data = _load("pandas.ledger-summary.json")
    ledger = data["sourceLedger"]
    assert ledger == {
        "source_loci": 8321,
        "source_warranted": 8321,
        "source_support": 0,
        "source_boundary": 0,
        "source_inactive": 0,
        "unclassified_source": 0,
        "source_unresolved": 0,
    }
    assert data["hasLineAccounting"] is False
    assert data["contracts"] == 8323


def test_itsdangerous_full_package_ledger_baseline() -> None:
    """Full-package itsdangerous (all 8 source files) differs sharply from
    the single-function slice fixture PR #3721 measured (R=7 on a 31-line
    slice, 2 warrant / 21 support / 1 effect). At full-package scope the
    lift completes (exit 0) but the ledger stays entirely zero: zero
    contracts, zero sourceAudits, despite 62 real refusal diagnostics
    (verify-dialect refusals per function). This is the exact, named,
    measured residue for the itsdangerous row -- not a silent skip.
    """
    data = _load("itsdangerous-full.ledger-summary.json")
    ledger = data["sourceLedger"]
    assert ledger == {
        "source_loci": 0,
        "source_warranted": 0,
        "source_support": 0,
        "source_boundary": 0,
        "source_inactive": 0,
        "unclassified_source": 0,
        "source_unresolved": 0,
    }
    assert data["hasLineAccounting"] is False
    assert data["contracts"] == 0
    assert data["diagnosticsCount"] == 62


def test_sklearn_lift_side_failure_baseline() -> None:
    """scikit-learn's whole-package lift dies loudly, not silently, on a
    named construction floor gap before any sourceLedger is produced. R is
    unmeasured (not zero, not silently skipped) until the floor gap is
    closed -- see #3731's retirement-path column for this row.
    """
    data = _load("sklearn.failure.json")
    assert data["measured"] is False
    assert data["failureShape"] == "lift-plugin-transport-error"
    assert data["exitCode"] == 2
    assert data["diagnostic"]["info"]["owner"] == "BinOpSugar"
    assert data["diagnostic"]["info"]["gap_kind"] == "Floor"
    assert "test_base.py:497:16" in data["diagnostic"]["info"]["blame"]
