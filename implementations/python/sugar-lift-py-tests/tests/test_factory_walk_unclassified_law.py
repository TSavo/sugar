"""Permanent baseline-free R_factory_walk_unclassified floor."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


from sugar_lift_py_tests.repo_root import sugar_lift_py_tests_package_root

_KIT = sugar_lift_py_tests_package_root()
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
        "statusCounts": {
            "warranted": 10,
            "support": 3,
            "unresolved": 4,
            "incomplete": 1,
        }
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
    assert (
        _SCANNER.r_factory_walk_unclassified(_SCANNER.extract_walk_rows(payload))
        == 1389
    )


def test_extract_from_factory_walk_statuses_aggregate() -> None:
    """Historical recensus shards emit factory_walk_statuses, not statusCounts."""
    payload = {
        "factory_walk_statuses": {"unclassified": 8470, "warranted": 75505},
        "census": {"files_total": 890},
    }
    rows = _SCANNER.extract_walk_rows(payload)
    assert _SCANNER.r_factory_walk_unclassified(rows) == 8470


def test_extract_prefers_row_addressable_locus_list_over_aggregate() -> None:
    """Next-recensus shape: retained loci win so reports print file:line, not ?:?:."""
    payload = {
        "R_factory_walk_unclassified": 99,
        "factory_walk_statuses": {"unclassified": 99},
        "factory_walk_unclassified_rows": [
            {
                "status": "unclassified",
                "selected": "",
                "ast_kind": "ListComp",
                "role": "term",
                "reason": "source-to-factory conservation owner disappeared",
                "file": "numpy/core/fromnumeric.py",
                "line": 42,
            },
            {
                "status": "unclassified",
                "selected": "CallSugar",
                "ast_kind": "Call",
                "role": "term",
                "reason": "no universe Sugar",
                "file": "numpy/core/numeric.py",
                "line": 7,
            },
        ],
    }
    rows = _SCANNER.extract_walk_rows(payload)
    assert _SCANNER.r_factory_walk_unclassified(rows) == 2
    assert rows[0]["file"] == "numpy/core/fromnumeric.py"
    assert rows[0]["line"] == 42
    report = _SCANNER.format_report(rows, limit=10)
    assert "numpy/core/fromnumeric.py:42" in report
    assert "?:?:" not in report


def test_extract_from_unclassified_rows_alias() -> None:
    payload = {
        "unclassified_rows": [
            {
                "status": "unclassified",
                "selected": "",
                "ast_kind": "GeneratorExp",
                "role": "term",
                "reason": "conservation owner disappeared",
                "file": "demo.py",
                "line": 3,
            }
        ]
    }
    rows = _SCANNER.extract_walk_rows(payload)
    assert _SCANNER.r_factory_walk_unclassified(rows) == 1
    assert rows[0]["file"] == "demo.py"


def test_extract_from_map_shaped_factory_walk() -> None:
    payload = {"factory_walk": {"unclassified": 12, "warranted": 40}}
    assert (
        _SCANNER.r_factory_walk_unclassified(_SCANNER.extract_walk_rows(payload)) == 12
    )


def test_extract_from_nested_accounting_factory() -> None:
    payload = {
        "accounting": {
            "factory": {"unclassified": 393, "warranted": 2061},
            "typed_effect": 26,
        }
    }
    assert (
        _SCANNER.r_factory_walk_unclassified(_SCANNER.extract_walk_rows(payload)) == 393
    )


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


def test_cli_live_root_measures_checked_in_python(tmp_path: Path, capsys) -> None:
    source = tmp_path / "clean.py"
    source.write_text("value = 1\nassert value == 1\n", encoding="utf-8")

    code = _SCANNER.main(
        [
            "--live-root",
            str(tmp_path),
            "--repo-root",
            str(tmp_path),
            "--workers",
            "1",
        ]
    )

    output = capsys.readouterr().out
    assert code == 0
    assert '"files_discovered": 1' in output
    assert '"files_completed": 1' in output
