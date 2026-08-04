"""The sole board seal refuses unattested frontier width.

These tests are consumer-side lying/truthful twins.  Producers are deliberately
not involved: commit one must make old producer output unmeasured before commit
two teaches the producers the witness schema.
"""

from __future__ import annotations

import copy
import importlib.util
import inspect
import json
import sys
from pathlib import Path

from sugar_lift_py_tests.repo_root import sugar_lift_py_tests_package_root

_SCRIPTS = sugar_lift_py_tests_package_root() / "scripts"
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


def _runtime_attestation(
    *,
    suffix: str = "a",
    invoked: str = "/venv/bin/python",
    version: str = "3.12.13",
    required_runtime: str | None = None,
):
    from sugar_lift_py_tests.authenticated_pytest import runtime_cid_for_identity

    identity = {
        "schema": "runtimeIdentity/v1",
        "implementation": "cpython",
        "version": version,
        "sysVersion": f"{version} test-build-{suffix}",
        "cacheTag": "cpython-312",
        "SOABI": "cpython-312-x86_64-linux-gnu",
        "hexVersion": "0x30c0df0",
        "platformTag": "Linux-test-x86_64-with-glibc2.39",
        "invokedExecutable": invoked,
        "resolvedBaseExecutable": "/runtime/bin/python3.12",
        "executableSha256": suffix * 64,
    }
    return {
        "requiredRuntime": required_runtime or f"cpython-{version}",
        "runtimeIdentity": identity,
        "runtimeCid": runtime_cid_for_identity(identity),
    }


def _runtime_identity_object(*, suffix: str = "a"):
    from sugar_lift_py_tests.authenticated_pytest import RuntimeIdentityV1

    wire = _runtime_attestation(suffix=suffix)["runtimeIdentity"]
    return RuntimeIdentityV1(
        implementation=wire["implementation"],
        version=wire["version"],
        sys_version=wire["sysVersion"],
        cache_tag=wire["cacheTag"],
        soabi=wire["SOABI"],
        hex_version=wire["hexVersion"],
        platform_tag=wire["platformTag"],
        invoked_executable=wire["invokedExecutable"],
        resolved_base_executable=wire["resolvedBaseExecutable"],
        executable_sha256=wire["executableSha256"],
    )


def _require_runtime_parameter(module) -> None:
    assert (
        "runtime_attestation"
        in inspect.signature(module.compose_k1_from_rows).parameters
    ), "compose can still mint a width without runtimeIdentity/v1"


def _compose(module, row, *, runtime_attestation=None):
    _require_runtime_parameter(module)
    return module.compose_k1_from_rows(
        [("pandas/a.py", row)],
        enrolled_files=["pandas/a.py"],
        measured_commit="4accd543",
        aggregate_hash="agg",
        manifest_shape_cid="manifest",
        runtime_attestation=(
            _runtime_attestation()
            if runtime_attestation is None
            else runtime_attestation
        ),
    )


def _assert_only_unmeasured(body):
    assert body["kind"] == "control-effect-recensus-unmeasured/v1"
    assert body["measured"] is False
    assert "frontierWidth" not in body
    assert "R_construction_panics" not in body
    assert "measurementClass" not in body


def test_compose_without_runtime_identity_refuses_before_width() -> None:
    module = _load()
    _require_runtime_parameter(module)
    status, body = module.compose_k1_from_rows(
        [("pandas/a.py", _row(module))],
        enrolled_files=["pandas/a.py"],
        measured_commit="4accd543",
        aggregate_hash="agg",
        manifest_shape_cid="manifest",
        runtime_attestation=None,
    )
    assert status == "unmeasured"
    _assert_only_unmeasured(body)
    assert body["runtimeIdentityFailure"] == "runtimeIdentity/v1 absent"


def test_compose_cli_wrong_runtime_refuses_before_reading_plan(
    tmp_path: Path, monkeypatch
) -> None:
    module = _load()
    import sugar_lift_py_tests.authenticated_pytest as runtime_authority

    observed = _runtime_identity_object(suffix="b")
    monkeypatch.setattr(
        runtime_authority, "observe_runtime_identity_v1", lambda: observed
    )

    def refuse(_identity):
        raise runtime_authority.ExecutionEnvironmentMismatch(
            "Python runtime authority mismatch: required cpython-3.12.13; "
            "observed locally patched cpython-3.12.13"
        )

    monkeypatch.setattr(runtime_authority, "authenticate_runtime_identity_v1", refuse)
    monkeypatch.setattr(
        runtime_authority,
        "declared_interpreter_runtime",
        lambda: "cpython-3.12.13",
    )
    out = tmp_path / "compose-unmeasured.json"

    exit_code = module.main(
        [
            "--plan",
            str(tmp_path / "missing-plan.json"),
            "--partials-dir",
            str(tmp_path / "missing-partials"),
            "--out",
            str(out),
        ]
    )

    assert exit_code == 1
    body = json.loads(out.read_text(encoding="utf-8"))
    assert body["status"] == "unmeasured"
    assert body["requiredRuntime"] == "cpython-3.12.13"
    assert body["runtimeIdentity"] == observed.to_wire()
    assert body["runtimeCid"] == runtime_authority.runtime_cid_for_identity(observed)
    assert "locally patched" in body["runtimeIdentityMismatch"]
    assert "frontierWidth" not in body


def test_partial_without_runtime_identity_refuses_at_compose() -> None:
    module = _load()
    _require_runtime_parameter(module)
    attestation = _runtime_attestation()
    plan = module.build_plan(
        enrolled_files=["pandas/a.py"],
        shard_count=1,
        measured_commit="4accd543",
        aggregate_hash="agg",
        manifest_shape_cid="manifest",
        bins=[["pandas/a.py"]],
        split_mode="test",
        prior_hits=0,
        prior_misses=1,
        estimated_loads=[0.0],
    )
    partial = module.mint_partial(
        plan=plan,
        shard_index=0,
        terminal_rows=[("pandas/a.py", _row(module))],
        runtime_attestation=attestation,
    )
    for field in ("requiredRuntime", "runtimeIdentity", "runtimeCid"):
        partial.pop(field)
    partial["partialCid"] = module.canonical_cid(
        {key: value for key, value in partial.items() if key != "partialCid"}
    )

    status, body = module.compose_from_partials(
        plan, [partial], runtime_attestation=attestation
    )
    assert status == "unmeasured"
    _assert_only_unmeasured(body)
    assert "runtimeIdentity/v1 absent" in body["unmeasuredReasons"]["s00"]


def test_non_recomputable_partial_runtime_cid_refuses() -> None:
    module = _load()
    _require_runtime_parameter(module)
    attestation = _runtime_attestation()
    plan = module.build_plan(
        enrolled_files=["pandas/a.py"],
        shard_count=1,
        measured_commit="4accd543",
        aggregate_hash="agg",
        manifest_shape_cid="manifest",
        bins=[["pandas/a.py"]],
        split_mode="test",
        prior_hits=0,
        prior_misses=1,
        estimated_loads=[0.0],
    )
    partial = module.mint_partial(
        plan=plan,
        shard_index=0,
        terminal_rows=[("pandas/a.py", _row(module))],
        runtime_attestation=attestation,
    )
    partial["runtimeCid"] = "blake3-512:" + ("0" * 128)
    partial["partialCid"] = module.canonical_cid(
        {key: value for key, value in partial.items() if key != "partialCid"}
    )

    status, body = module.compose_from_partials(
        plan, [partial], runtime_attestation=attestation
    )
    assert status == "unmeasured"
    _assert_only_unmeasured(body)
    assert "runtimeCid is not recomputable" in body["unmeasuredReasons"]["s00"]


def test_valid_but_disagreeing_shard_runtime_cids_refuse() -> None:
    module = _load()
    _require_runtime_parameter(module)
    left = _runtime_attestation(suffix="a")
    right = _runtime_attestation(suffix="b")
    plan = module.build_plan(
        enrolled_files=["pandas/a.py", "pandas/b.py"],
        shard_count=2,
        measured_commit="4accd543",
        aggregate_hash="agg",
        manifest_shape_cid="manifest",
        bins=[["pandas/a.py"], ["pandas/b.py"]],
        split_mode="test",
        prior_hits=0,
        prior_misses=2,
        estimated_loads=[0.0, 0.0],
    )
    partials = [
        module.mint_partial(
            plan=plan,
            shard_index=0,
            terminal_rows=[("pandas/a.py", _row(module))],
            runtime_attestation=left,
        ),
        module.mint_partial(
            plan=plan,
            shard_index=1,
            terminal_rows=[("pandas/b.py", _row(module, key=_key("pandas/b.py", "g")))],
            runtime_attestation=right,
        ),
    ]

    status, body = module.compose_from_partials(
        plan, partials, runtime_attestation=left
    )
    assert status == "unmeasured"
    _assert_only_unmeasured(body)
    assert "runtimeCid disagrees" in body["unmeasuredReasons"]["s01"]


def test_well_formed_shard_runtime_wrong_for_compose_authority_refuses() -> None:
    module = _load()
    _require_runtime_parameter(module)
    executing = _runtime_attestation(suffix="a")
    forged = _runtime_attestation(suffix="b")
    plan = module.build_plan(
        enrolled_files=["pandas/a.py"],
        shard_count=1,
        measured_commit="4accd543",
        aggregate_hash="agg",
        manifest_shape_cid="manifest",
        bins=[["pandas/a.py"]],
        split_mode="test",
        prior_hits=0,
        prior_misses=1,
        estimated_loads=[0.0],
    )
    partial = module.mint_partial(
        plan=plan,
        shard_index=0,
        terminal_rows=[("pandas/a.py", _row(module))],
        runtime_attestation=forged,
    )

    status, body = module.compose_from_partials(
        plan, [partial], runtime_attestation=executing
    )
    assert status == "unmeasured"
    _assert_only_unmeasured(body)
    assert (
        "runtimeCid mismatches authenticated compose runtime"
        in body["unmeasuredReasons"]["s00"]
    )


def test_shards_agree_with_each_other_but_not_required_runtime_refuse() -> None:
    module = _load()
    _require_runtime_parameter(module)
    executing = _runtime_attestation(suffix="a")
    mutually_agreeing_wrong_runtime = _runtime_attestation(
        suffix="b",
        version="3.12.14",
        required_runtime="cpython-3.12.14",
    )
    plan = module.build_plan(
        enrolled_files=["pandas/a.py", "pandas/b.py"],
        shard_count=2,
        measured_commit="4accd543",
        aggregate_hash="agg",
        manifest_shape_cid="manifest",
        bins=[["pandas/a.py"], ["pandas/b.py"]],
        split_mode="test",
        prior_hits=0,
        prior_misses=2,
        estimated_loads=[0.0, 0.0],
    )
    partials = [
        module.mint_partial(
            plan=plan,
            shard_index=0,
            terminal_rows=[("pandas/a.py", _row(module))],
            runtime_attestation=mutually_agreeing_wrong_runtime,
        ),
        module.mint_partial(
            plan=plan,
            shard_index=1,
            terminal_rows=[("pandas/b.py", _row(module, key=_key("pandas/b.py", "g")))],
            runtime_attestation=mutually_agreeing_wrong_runtime,
        ),
    ]

    status, body = module.compose_from_partials(
        plan, partials, runtime_attestation=executing
    )
    assert status == "unmeasured"
    _assert_only_unmeasured(body)
    assert all(
        "requiredRuntime mismatches authenticated compose requirement"
        in body["unmeasuredReasons"][seat]
        for seat in ("s00", "s01")
    )


def test_runtime_identity_is_inside_body_cid_but_paths_are_outside_runtime_cid() -> (
    None
):
    module = _load()
    _require_runtime_parameter(module)
    first = _runtime_attestation(invoked="/venv-a/bin/python")
    moved = copy.deepcopy(first)
    moved["runtimeIdentity"]["invokedExecutable"] = "/venv-b/bin/python"
    assert moved["runtimeCid"] == first["runtimeCid"]

    left_status, left = _compose(module, _row(module), runtime_attestation=first)
    right_status, right = _compose(module, _row(module), runtime_attestation=moved)

    assert left_status == right_status == "sealed"
    assert left["runtimeCid"] == right["runtimeCid"]
    assert (
        left["runtimeIdentity"]["invokedExecutable"]
        != right["runtimeIdentity"]["invokedExecutable"]
    )
    assert left["bodyCid"] != right["bodyCid"]


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
    assert any("stageId" in str(f.get("reason")) for f in body["instrumentFailures"])


def test_claimed_key_cid_mismatch_refuses() -> None:
    module = _load()
    row = _row(module)
    row["edgeWitnesses"][module.EDGE_ENUMERATE_FILE]["inputKeyCid"] = "sha256:" + (
        "0" * 64
    )
    status, body = _compose(module, row)
    assert status == "unmeasured"
    _assert_only_unmeasured(body)
    assert any(
        f.get("reason") == "inputKeyCid mismatch" for f in body["instrumentFailures"]
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
    assert any(f.get("duplicateKeys") for f in body["instrumentFailures"])


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
            "observedEventType": ("sugar_lift_py_tests.gap.panic.ConstructionPanic"),
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
        assert edge["inputKeyCid"] == module.key_manifest_cid(edge["inputKeyManifest"])
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


def test_direct_board_seal_cannot_bypass_runtime_identity() -> None:
    module = _load()
    row = _row(module)
    aggregate = module.aggregate_terminal_rows(
        [("pandas/a.py", row)],
        enrolled_files=["pandas/a.py"],
    )
    attestation, failures = module.attest_frontier_rows([("pandas/a.py", row)])
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
        runtime_attestation=None,
    )

    assert body["status"] == "unmeasured"
    assert body["runtimeIdentityFailure"] == "runtimeIdentity/v1 absent"
    assert "frontierWidth" not in body
    assert "measurementClass" not in body
    assert "bodyCid" not in body


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
    attestation, failures = module.attest_frontier_rows([("pandas/a.py", row)])
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
        runtime_attestation=_runtime_attestation(),
    )
    assert body["measurement"] == "unmeasured"
    assert "frontierWidth" not in body
    assert "R_construction_panics" not in body
    assert "conservationWitness" not in body
