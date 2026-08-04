"""Conservation teeth for the #5330 pandas timeout-residual disposition."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


from repo_root_test_support import resolve_repo_root

REPO_ROOT = resolve_repo_root()
SOURCE_LEDGER = (
    REPO_ROOT / "docs/ledgers/pandas-timeout-shared-mechanism-5306.json"
)
DISPOSITION_LEDGER = (
    REPO_ROOT / "docs/ledgers/pandas-timeout-residual-disposition-5330.json"
)
ALLOWED_DISPOSITIONS = {
    "completed",
    "typed-factory-panic",
    "bare-exception",
    "timeout-second-mechanism",
    "timeout-irreducible",
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_exact_residual_manifest_has_one_honest_disposition_per_file() -> None:
    source = _load(SOURCE_LEDGER)
    ledger = _load(DISPOSITION_LEDGER)

    expected_files = {
        row["file"]
        for row in source["files"]
        if row["disposition"] == "timeout-or-hang"
    }
    rows = ledger["files"]
    actual_files = [row["file"] for row in rows]
    dispositions = Counter(row["disposition"] for row in rows)

    assert len(expected_files) == 66
    assert len(actual_files) == len(set(actual_files)), "duplicate file disposition"
    assert set(actual_files) == expected_files
    assert set(dispositions) <= ALLOWED_DISPOSITIONS
    assert sum(dispositions.values()) == 66
    assert dispositions == Counter(ledger["conservation"])
    assert ledger["conservation"]["silent"] == 0
    assert ledger["timeout_classes"]["second_multiplicative_mechanism"] == []
    assert ledger["timeout_classes"]["genuinely_irreducible"] == []


def test_noncompleted_rows_keep_loud_terminal_testimony() -> None:
    ledger = _load(DISPOSITION_LEDGER)

    for row in ledger["files"]:
        if row["disposition"] == "completed":
            assert row["terminal"] is None
        else:
            assert row["terminal"] is not None
            assert row["terminal"]["kind"] != "runtime-effect"


def test_deferred_statement_memo_does_not_claim_timeout_retirement() -> None:
    ledger = _load(DISPOSITION_LEDGER)
    review = ledger["coordination"]["pr_5336"]

    assert review["retired_timeout_files_from_66"] == 0
    assert "unsound cache identity" in review["soundness"]
    assert "fresh build returns x=2" in review["counterexample"]
