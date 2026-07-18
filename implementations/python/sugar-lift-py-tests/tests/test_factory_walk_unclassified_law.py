"""Permanent baseline-free R_factory_walk_unclassified floor."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


_KIT = Path(__file__).resolve().parents[1]
_SCANNER_PATH = _KIT / "scripts" / "factory_walk_unclassified_law.py"
_SPEC = importlib.util.spec_from_file_location(
    "factory_walk_unclassified_law", _SCANNER_PATH
)
assert _SPEC is not None and _SPEC.loader is not None
_SCANNER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_SCANNER)


def test_planted_unclassified_rows_trip_floor() -> None:
    rows = [
        {"status": "warranted", "file": "a.py", "line": 1},
        {"status": "unclassified", "file": "b.py", "line": 2, "reason": "no owner"},
        {"status": "unresolved", "file": "c.py", "line": 3, "reason": "gap"},
        {"status": "support", "file": "d.py", "line": 4},
        {"status": "raise-effect", "file": "e.py", "line": 5, "reason": "typed"},
    ]
    assert _SCANNER.r_factory_walk_unclassified(rows) == 2


def test_clean_walk_is_zero() -> None:
    rows = [
        {"status": "warranted"},
        {"status": "support"},
        {"status": "raise-effect", "reason": "typed"},
        {"status": "runtime-effect", "reason": "typed"},
    ]
    assert _SCANNER.r_factory_walk_unclassified(rows) == 0


def test_extract_from_audit_summary_status_counts() -> None:
    payload = {
        "statusCounts": {"warranted": 10, "support": 3, "unresolved": 4, "incomplete": 1}
    }
    rows = _SCANNER.extract_walk_rows(payload)
    assert _SCANNER.r_factory_walk_unclassified(rows) == 4


def test_extract_from_recensus_red_statuses() -> None:
    payload = {
        "factory_walk_red_statuses": {
            "unclassified": 1389,
            "raise-effect": 12,
        }
    }
    assert _SCANNER.r_factory_walk_unclassified(_SCANNER.extract_walk_rows(payload)) == 1389


def test_cli_red_on_planted_json(tmp_path: Path) -> None:
    path = tmp_path / "walk.json"
    path.write_text(
        json.dumps(
            [
                {"status": "warranted"},
                {
                    "status": "unclassified",
                    "file": "x.py",
                    "line": 9,
                    "reason": "missing Sugar",
                },
            ]
        ),
        encoding="utf-8",
    )
    code = _SCANNER.main(["--from-json", str(path)])
    assert code == 1


def test_cli_green_on_clean_json(tmp_path: Path) -> None:
    path = tmp_path / "walk.json"
    path.write_text(
        json.dumps([{"status": "warranted"}, {"status": "support"}]),
        encoding="utf-8",
    )
    code = _SCANNER.main(["--from-json", str(path)])
    assert code == 0


def test_cli_refuses_missing_measurement() -> None:
    code = _SCANNER.main([])
    assert code == 2


def test_cli_structured_error_on_bad_json(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{not-json", encoding="utf-8")
    code = _SCANNER.main(["--from-json", str(path)])
    assert code == 2
