"""Board numbers: one name, one meaning (files + functions + panic counts)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "compose_control_effect_board.py"
)


def _load_compose():
    spec = importlib.util.spec_from_file_location(
        "compose_control_effect_board_meanings", _SCRIPT
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_functions_three_meanings_not_one_figure() -> None:
    """Population / enumerated / clean are three sealed facts, not one int."""
    from sugar_lift_py_tests.c4.board_function_facts import (
        LocalReading,
        board_fields_from_sealed_facts,
        seal_functions_clean_v1,
        seal_functions_enumerated_v1,
        seal_functions_population_v1,
    )

    tip = "deadbeef"
    pin = "pin-test"
    pop = seal_functions_population_v1(
        LocalReading(100, "pop"), tip=tip, pin=pin
    )
    enum = seal_functions_enumerated_v1(
        LocalReading(90, "enum"), tip=tip, pin=pin
    )
    clean = seal_functions_clean_v1(
        LocalReading(80, "clean"), tip=tip, pin=pin, refused=False
    )
    fields = board_fields_from_sealed_facts(pop, enum, clean)
    assert fields["functionsTotal"] == 100
    assert fields["functionsEnumerated"] == 90
    assert fields["functionsUnaccounted"] == 10
    assert fields["functionsConstructClean"] == 80
    assert fields["cleanRatioRefused"] is False
    # Three distinct fact CIDs — not one body wearing three labels.
    cids = fields["sealedFactCids"]
    assert len(set(cids.values())) == 3


def test_seal_board_splits_file_and_residual_meanings() -> None:
    """Compose seals enrolled/terminal/completed/panicked separately."""
    mod = _load_compose()
    agg = {
        "families": {},
        "desugar_families": {},
        "desugar_categories": {},
        "desugar_by_category_owner": {},
        "backend_defects": {},
        "cm_resolutions": {"constructed": 3, "unconstructed": 1},
        "unrecognized_cm_kinds": {},
        "ast_sites": {},
        "desugar_construction_panics": [{"file": "a.py", "type": "Panic"}],
        "desugar_defects": [],
        "desugar_designed_gaps": [],
        "unresolvable_dispatch": [],
        "construction_panics": [
            {"file": "p.py", "type": "SugarNotWritten", "message": "unwritten"}
        ],
        "defects": [{"file": "p.py", "type": "panic", "message": "unwritten"}],
        "floor_rows": [],
        "files_completed": 2,
        "files_panicked": 1,
        "functions_total": 10,
        "functions_clean": 7,
        "functions_enumerated": 9,
        "clean_ratio_refused": False,
        "clean_refuse_reasons": [],
        "r_instrument_blind": 0,
        "r_instrument_blind_functions": 0,
        "missing_files": ["missing.py"],
        "duplicate_files": [],
        "malformed_rows": [],
        "files_complete": False,
        "enrolled_files": ["a.py", "b.py", "p.py", "missing.py"],
        "terminal_count": 3,
        "manifest_cid": None,
    }
    body = mod.seal_board_from_aggregate(
        agg,
        plan=None,
        per_shard_cids=None,
        compose_cid=None,
        measured_commit="abc123",
        aggregate_hash="pin-hash",
    )
    # Files unit
    assert body["filesEnrolled"] == 4
    assert body["filesTerminal"] == 3
    assert body["filesCompleted"] == 2
    assert body["filesPanicked"] == 1
    assert body["filesMissing"] == 1
    assert body["filesTotal"] == body["filesEnrolled"]  # alias only
    # Functions unit
    assert body["functionsPopulation"] == 10
    assert body["functionsEnumerated"] == 9
    assert body["functionsUnaccounted"] == 1
    assert body["functionsConstructClean"] == 7
    # Residual = panic counts, not bag totals
    assert body["R_construction_panics"] == 1
    assert body["R_desugar_construction_panics"] == 1
    assert body["R_desugar_defects"] == 0
    assert body["R_cm_constructed"] == 3
    assert body["R_cm_unconstructed"] == 1
    assert "R_construction" not in body  # bag total deleted
    assert "R" not in body or body.get("R") is None
    assert "boardNumberMeanings" in body
