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

    def row(
        file: str,
        *,
        category: str,
        functions_total: int,
        functions_enumerated: int,
        functions_clean: int,
        cm_resolutions: dict[str, int],
        desugar_panics: list[dict[str, str]] | None = None,
    ) -> dict[str, object]:
        input_key = {
            "file": file,
            "sourceCid": "sha256:" + (file[0] * 64),
            "function": {"qualname": "f", "coordinate": "1:0"},
        }
        is_panic = category == "panic"
        result: dict[str, object] = {
            "category": category,
            "functionsTotal": functions_total,
            "functionsEnumerated": functions_enumerated,
            "functionsClean": functions_clean,
            "cleanRatioRefused": False,
            "families": {},
            "cmResolutions": cm_resolutions,
            "desugarConstructionPanics": desugar_panics or [],
            "inputKey": input_key,
            "rowId": mod.canonical_cid({"inputKey": input_key}),
            "stageId": mod.STAGE_ENUMERATE_FILE_TERMINAL,
            "observedEventType": (
                mod._CONSTRUCTION_PANIC_TYPE
                if is_panic
                else "sugar_lift_py_tests.outcome.Complete"
            ),
            "terminalKind": "construction-panic" if is_panic else "constructed",
            "observed_chain_length": 2 if is_panic else 1,
            "blocking_terminal_count": 1 if is_panic else 0,
            "final_terminal": "construction-panic" if is_panic else "constructed",
            "edgeWitnesses": {
                mod.EDGE_ENUMERATE_FILE: mod.key_edge_witness(
                    stage_id=mod.STAGE_ENUMERATE_FILE_TERMINAL,
                    input_keys=[input_key],
                    output_keys=[input_key],
                ),
                mod.EDGE_WITH_PARTITION: mod.key_edge_witness(
                    stage_id=mod.STAGE_WITH_TALLY_PARTITION,
                    input_keys=[],
                    output_keys=[],
                ),
            },
        }
        if is_panic:
            result["panic"] = {
                "owner": "WithSugar",
                "coordinate": f"{file}:1:0",
                "observed": "opaque manager",
                "requested": "constructed With",
                "fix": "write the missing With construction",
                "entrance": "sugar.enumerate",
                "construction_trace": ["sugar.enumerate", "WithSugar"],
            }
        return result

    rows = [
        (
            "a.py",
            row(
                "a.py",
                category="completed",
                functions_total=3,
                functions_enumerated=3,
                functions_clean=2,
                cm_resolutions={"constructed": 1},
            ),
        ),
        (
            "b.py",
            row(
                "b.py",
                category="completed",
                functions_total=3,
                functions_enumerated=3,
                functions_clean=2,
                cm_resolutions={"constructed": 1},
            ),
        ),
        (
            "c.py",
            row(
                "c.py",
                category="completed",
                functions_total=2,
                functions_enumerated=2,
                functions_clean=2,
                cm_resolutions={"constructed": 1},
            ),
        ),
        (
            "p.py",
            row(
                "p.py",
                category="panic",
                functions_total=2,
                functions_enumerated=1,
                functions_clean=1,
                cm_resolutions={"unconstructed": 1},
                desugar_panics=[{"file": "p.py", "type": "ConstructionPanic"}],
            ),
        ),
    ]
    status, body = mod.compose_k1_from_rows(
        rows,
        enrolled_files=[file for file, _ in rows],
        measured_commit="abc123",
        aggregate_hash="pin-hash",
        manifest_shape_cid="manifest",
    )
    assert status == "sealed", body.get("instrumentFailures")
    assert body["filesEnrolled"] == 4
    assert body["filesTerminal"] == 4
    assert body["filesCompleted"] == 3
    assert body["filesPanicked"] == 1
    assert body["filesMissing"] == 0
    assert body["filesTotal"] == body["filesEnrolled"]
    assert body["functionsPopulation"] == 10
    assert body["functionsEnumerated"] == 9
    assert body["functionsUnaccounted"] == 1
    assert body["functionsConstructClean"] == 7
    assert body["R_construction_panics"] == 1
    assert body["R_desugar_construction_panics"] == 1
    assert body["R_cm_constructed"] == 3
    assert body["R_cm_unconstructed"] == 1
    assert "R_desugar_defects" not in body
    assert "R_desugar_owed_work" not in body
    assert "R_desugar_accounted_semantics" not in body
    assert "R_construction" not in body
    assert "R" not in body
    assert "boardNumberMeanings" in body


def test_direct_board_mint_without_frontier_witness_is_unmeasured() -> None:
    """A formatter cannot emit census magnitudes around the compose validator."""
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
    assert body["measurement"] == "unmeasured"
    assert body["kind"] == "measurement-conservation-failure-v1"
    assert "conservationWitness" not in body
    assert "R_construction_panics" not in body
    assert "functionsPopulation" not in body
