"""The sole board seal refuses unattested frontier width.

These tests are consumer-side lying/truthful twins.  Producers are deliberately
not involved: commit one must make old producer output unmeasured before commit
two teaches the producers the witness schema.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
_SCRIPT = _SCRIPTS / "compose_control_effect_board.py"


def _load():
    if str(_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS))
    spec = importlib.util.spec_from_file_location(
        "compose_control_effect_board_frontier", _SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _key(file: str = "pandas/a.py", function: str = "f") -> dict[str, object]:
    return {
        "file": file,
        "sourceCid": "sha256:" + ("a" * 64),
        "function": {"qualname": function, "coordinate": "1:0"},
    }


def _row(module, *, key=None, with_inputs=(), with_outputs=()):
    input_key = key or _key()
    return {
        "category": "completed",
        "functionsTotal": 1,
        "functionsEnumerated": 1,
        "functionsClean": 1,
        "cleanRatioRefused": False,
        "families": {},
        "inputKey": input_key,
        "rowId": module.canonical_cid({"inputKey": input_key}),
        "stageId": module.STAGE_ENUMERATE_FILE_TERMINAL,
        "observedEventType": "sugar_lift_py_tests.outcome.Complete",
        "terminalKind": "constructed",
        "observed_chain_length": 1,
        "blocking_terminal_count": 0,
        "final_terminal": "constructed",
        "edgeWitnesses": {
            module.EDGE_ENUMERATE_FILE: module.key_edge_witness(
                stage_id=module.STAGE_ENUMERATE_FILE_TERMINAL,
                input_keys=[input_key],
                output_keys=[input_key],
            ),
            module.EDGE_WITH_PARTITION: module.key_edge_witness(
                stage_id=module.STAGE_WITH_TALLY_PARTITION,
                input_keys=list(with_inputs),
                output_keys=list(with_outputs),
            ),
        },
    }


def _compose(module, row):
    return module.compose_k1_from_rows(
        [("pandas/a.py", row)],
        enrolled_files=["pandas/a.py"],
        measured_commit="4accd543",
        aggregate_hash="agg",
        manifest_shape_cid="manifest",
    )


def _assert_only_unmeasured(body):
    assert body["kind"] == "control-effect-recensus-unmeasured/v1"
    assert body["measured"] is False
    assert "frontierWidth" not in body
    assert "R_construction_panics" not in body
    assert "measurementClass" not in body


def test_truthful_current_main_with_collapse_refuses() -> None:
    """4accd543: tally has two canonical rows; stale partition consumes none."""
    module = _load()
    with_rows = [
        {"sourceCid": "sha256:" + ("b" * 64), "coordinate": "10:4"},
        {"sourceCid": "sha256:" + ("b" * 64), "coordinate": "11:4"},
    ]
    status, body = _compose(
        module,
        _row(module, with_inputs=with_rows, with_outputs=[]),
    )
    assert status == "unmeasured"
    _assert_only_unmeasured(body)
    failure = next(
        f
        for f in body["instrumentFailures"]
        if f.get("edgeId") == module.EDGE_WITH_PARTITION
    )
    assert failure["inputKeyCount"] == 2
    assert failure["outputKeyCount"] == 0
    assert failure["missingKeys"] == with_rows


def test_equal_count_substitution_refuses() -> None:
    module = _load()
    original = {
        "sourceCid": "sha256:" + ("b" * 64),
        "coordinate": "10:4",
    }
    substitute = {
        "sourceCid": "sha256:" + ("b" * 64),
        "coordinate": "99:4",
    }
    status, body = _compose(
        module,
        _row(module, with_inputs=[original], with_outputs=[substitute]),
    )
    assert status == "unmeasured"
    _assert_only_unmeasured(body)
    failure = next(
        f
        for f in body["instrumentFailures"]
        if f.get("edgeId") == module.EDGE_WITH_PARTITION
    )
    assert failure["inputKeyCount"] == failure["outputKeyCount"] == 1
    assert failure["missingKeys"] == [original]
    assert failure["extraKeys"] == [substitute]


def test_missing_stage_testimony_refuses() -> None:
    module = _load()
    row = _row(module)
    row["edgeWitnesses"][module.EDGE_WITH_PARTITION].pop("stageId")
    status, body = _compose(module, row)
    assert status == "unmeasured"
    _assert_only_unmeasured(body)
    assert any(
        "stageId" in str(f.get("reason")) for f in body["instrumentFailures"]
    )


def test_claimed_key_cid_mismatch_refuses() -> None:
    module = _load()
    row = _row(module)
    row["edgeWitnesses"][module.EDGE_ENUMERATE_FILE]["inputKeyCid"] = (
        "sha256:" + ("0" * 64)
    )
    status, body = _compose(module, row)
    assert status == "unmeasured"
    _assert_only_unmeasured(body)
    assert any(
        f.get("reason") == "inputKeyCid mismatch"
        for f in body["instrumentFailures"]
    )


def test_duplicate_key_rows_refuse_even_when_both_sides_match() -> None:
    module = _load()
    row = _row(module)
    key = row["inputKey"]
    row["edgeWitnesses"][module.EDGE_WITH_PARTITION] = module.key_edge_witness(
        stage_id=module.STAGE_WITH_TALLY_PARTITION,
        input_keys=[key, key],
        output_keys=[key, key],
    )
    status, body = _compose(module, row)
    assert status == "unmeasured"
    _assert_only_unmeasured(body)
    assert any(
        f.get("duplicateKeys") for f in body["instrumentFailures"]
    )


def test_explicit_instrument_exception_refuses() -> None:
    module = _load()
    row = _row(module)
    row["instrumentFailure"] = {
        "observedEventType": "builtins.AssertionError",
        "message": "classifier arm unreachable",
    }
    status, body = _compose(module, row)
    assert status == "unmeasured"
    _assert_only_unmeasured(body)
    assert any(
        f.get("observedEventType") == "builtins.AssertionError"
        for f in body["instrumentFailures"]
    )


def test_ordinary_exception_relabelled_as_panic_refuses() -> None:
    module = _load()
    row = _row(module)
    row.update(
        {
            "category": "panic",
            "terminalKind": "construction-panic",
            "observedEventType": "builtins.NameError",
            "blocking_terminal_count": 1,
            "final_terminal": "construction-panic",
            "panic": {
                "owner": "WithSugar",
                "coordinate": "pandas/a.py:1:0",
                "observed": "NameError",
                "requested": "constructed With",
                "fix": "import the missing instrument symbol",
                "entrance": "sugar.enumerate",
                "construction_trace": ["sugar.enumerate", "WithSugar"],
            },
        }
    )
    status, body = _compose(module, row)
    assert status == "unmeasured"
    _assert_only_unmeasured(body)
    assert any(
        f.get("observedEventType") == "builtins.NameError"
        for f in body["instrumentFailures"]
    )


def test_construction_panic_without_required_payload_refuses() -> None:
    module = _load()
    row = _row(module)
    row.update(
        {
            "category": "panic",
            "terminalKind": "construction-panic",
            "observedEventType": (
                "sugar_lift_py_tests.gap.panic.ConstructionPanic"
            ),
            "blocking_terminal_count": 1,
            "final_terminal": "construction-panic",
            "panic": {"owner": "WithSugar", "coordinate": "pandas/a.py:1:0"},
        }
    )
    status, body = _compose(module, row)
    assert status == "unmeasured"
    _assert_only_unmeasured(body)
    assert any(
        f.get("reason") == "non-authenticated ConstructionPanic payload"
        for f in body["instrumentFailures"]
    )


def test_truthful_attested_row_seals_and_carries_recomputable_manifests() -> None:
    module = _load()
    status, body = _compose(module, _row(module))
    assert status == "sealed"
    assert body["measurement"] == "measured"
    witness = body["conservationWitness"]
    assert witness["witnessSchema"] == "sugar.conservation-witness.v1"
    assert witness["validatorStageId"] == module.STAGE_TERMINAL_AGGREGATE_SEAL
    assert witness["status"] == "passed"
    from sugar_lift_py_tests.conservation_mint import decode_conserved_body

    assert decode_conserved_body(body).witness.to_wire() == witness
    assert body["filesEnrolled"] == 1
    assert body["filesTerminal"] == 1
    assert body["filesCompleted"] == 1
    assert body["filesPanicked"] == 0
    assert body["filesMissing"] == 0
    assert body["functionsPopulation"] == 1
    assert body["functionsEnumerated"] == 1
    assert body["functionsConstructClean"] == 1
    assert body["R_construction_panics"] == 0
    assert "boardNumberMeanings" in body
    assert body["frontierWidth"] == 0
    attestation = body["frontierAttestation"]
    assert set(attestation["edges"]) == {
        module.EDGE_ENUMERATE_FILE,
        module.EDGE_WITH_PARTITION,
        module.EDGE_TERMINAL_SEAL,
    }
    for edge in attestation["edges"].values():
        assert edge["inputKeyCount"] == len(edge["inputKeyManifest"])
        assert edge["outputKeyCount"] == len(edge["outputKeyManifest"])
        assert edge["inputKeyCid"] == module.key_manifest_cid(
            edge["inputKeyManifest"]
        )
        assert edge["outputKeyCid"] == module.key_manifest_cid(
            edge["outputKeyManifest"]
        )
        assert edge["missingKeys"] == []
        assert edge["extraKeys"] == []
        assert edge["duplicateKeys"] == []
    assert attestation["instrumentFailures"] == []
    assert attestation["terminalConvention"] == {
        "observed_chain_length": "number of observed terminals in order",
        "blocking_terminal_count": "number of terminals that blocked construction",
        "final_terminal": "last observed terminal, separate from both counts",
    }


def test_aggregate_panic_magnitude_cannot_disagree_with_attested_keys() -> None:
    module = _load()
    row = _row(module)
    aggregate = module.aggregate_terminal_rows(
        [("pandas/a.py", row)],
        enrolled_files=["pandas/a.py"],
    )
    aggregate["construction_panics"].append(
        {"owner": "LyingAggregate", "coordinate": "pandas/a.py:99:0"}
    )
    attestation, failures = module.attest_frontier_rows(
        [("pandas/a.py", row)]
    )
    assert failures == []
    body = module.seal_board_from_aggregate(
        aggregate,
        plan=None,
        per_shard_cids=None,
        compose_cid=None,
        measured_commit="4accd543",
        aggregate_hash="agg",
        manifest_shape_cid="manifest",
        frontier_attestation=attestation,
    )
    assert body["measurement"] == "unmeasured"
    assert "frontierWidth" not in body
    assert "R_construction_panics" not in body
    assert "conservationWitness" not in body
