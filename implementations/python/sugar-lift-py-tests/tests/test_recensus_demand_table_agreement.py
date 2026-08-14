"""One demand-table meaning must bind every recensus shard.

The truthful and lying twins are deliberately compose-side.  A plan and all
eight partials may agree on every other seal while one table claim is absent or
different; neither case may mint a frontier width.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from sugar_lift_py_tests.authenticated_pytest import runtime_cid_for_identity
from sugar_lift_py_tests.demand_table_identity import DemandTableIdentityV1
from sugar_lift_python_source.canonical import cid_of_json
from sugar_lift_py_tests.repo_root import sugar_lift_py_tests_package_root


_SCRIPTS = sugar_lift_py_tests_package_root() / "scripts"
_SCRIPT = _SCRIPTS / "compose_control_effect_board.py"


def _load():
    if str(_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS))
    spec = importlib.util.spec_from_file_location(
        "compose_control_effect_board_demand_table_agreement", _SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _runtime_attestation() -> dict[str, object]:
    identity = {
        "schema": "runtimeIdentity/v1",
        "implementation": "cpython",
        "version": "3.12.13",
        "sysVersion": "3.12.13 demand-table-agreement-test",
        "cacheTag": "cpython-312",
        "SOABI": "cpython-312-x86_64-linux-gnu",
        "hexVersion": "0x30c0df0",
        "platformTag": "Linux-test-x86_64-with-glibc2.39",
        "invokedExecutable": "/venv/bin/python",
        "resolvedBaseExecutable": "/runtime/bin/python3.12",
        "executableSha256": "a" * 64,
    }
    return {
        "requiredRuntime": "cpython-3.12.13",
        "runtimeIdentity": identity,
        "runtimeCid": runtime_cid_for_identity(identity),
    }


def _demand_identity(*, suffix: str = "a") -> dict[str, object]:
    identity = DemandTableIdentityV1(
        content_key="",
        corpus_manifest_cid=f"blake3-512:corpus-{suffix}",
        schema_version="python-demand-table/v1",
        producer_source_cid=f"blake3-512:producer-{suffix}",
        resolution_config_cid=f"blake3-512:config-{suffix}",
        parser_identity="cpython-3.12",
        file_count=8,
    )
    return DemandTableIdentityV1(
        content_key=cid_of_json(dict(identity.preimage())),
        corpus_manifest_cid=identity.corpus_manifest_cid,
        schema_version=identity.schema_version,
        producer_source_cid=identity.producer_source_cid,
        resolution_config_cid=identity.resolution_config_cid,
        parser_identity=identity.parser_identity,
        file_count=identity.file_count,
    ).as_dict()


def _row(module, file: str) -> dict[str, object]:
    input_key = {
        "file": file,
        "sourceCid": module.canonical_cid({"file": file}),
        "function": {"qualname": "f", "coordinate": "1:0"},
    }
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
                input_keys=[],
                output_keys=[],
            ),
        },
    }


def _plan(module, *, cid: str, identity: dict[str, object]):
    files = [f"pandas/f{i}.py" for i in range(8)]
    return module.build_plan(
        enrolled_files=files,
        shard_count=8,
        measured_commit="dc41472e64",
        aggregate_hash="agg",
        manifest_shape_cid="manifest",
        bins=[[file] for file in files],
        split_mode="fixture",
        prior_hits=0,
        prior_misses=8,
        estimated_loads=[1.0] * 8,
        demand_table_cid=cid,
        demand_table_identity=identity,
    )


def _partials(
    module,
    plan,
    *,
    cid: str,
    identity: dict[str, object],
    lying_index: int | None = None,
    absent_index: int | None = None,
):
    runtime = _runtime_attestation()
    rows = []
    for index, (file,) in enumerate(plan["bins"]):
        observed_cid = None if index == absent_index else cid
        observed_identity = None if index == absent_index else identity
        if index == lying_index:
            observed_cid = "blake3-512:different-table"
            observed_identity = _demand_identity(suffix="b")
        rows.append(
            module.mint_partial(
                plan=plan,
                shard_index=index,
                terminal_rows=[(file, _row(module, file))],
                demand_table_cid=observed_cid,
                demand_table_identity=observed_identity,
                relation_membership_attestation=_relation_membership(
                    module, [file]
                ),
                runtime_attestation=runtime,
            )
        )
    return rows


def _assert_unmeasured_without_width(body: dict[str, object]) -> None:
    assert body["kind"] == "control-effect-recensus-unmeasured/v1"
    assert body["status"] == "unmeasured"
    assert body["measured"] is False
    assert "frontierWidth" not in body
    assert "bodyCid" not in body


def _direct_seal(
    module,
    *,
    demand_table_agreement,
) -> dict[str, object]:
    cid = "blake3-512:table-a"
    identity = _demand_identity()
    plan = _plan(module, cid=cid, identity=identity)
    measured_rows = [
        (file, _row(module, file)) for file in plan["enrolledFiles"]
    ]
    aggregate = module.aggregate_terminal_rows(
        measured_rows,
        enrolled_files=plan["enrolledFiles"],
        manifest_cid="manifest",
    )
    frontier, failures = module.attest_frontier_rows(measured_rows)
    assert failures == []
    return module.seal_board_from_aggregate(
        aggregate,
        plan=plan,
        per_shard_cids={f"s{i:02d}": f"partial-{i}" for i in range(8)},
        compose_cid="blake3-512:compose",
        measured_commit="dc41472e64",
        frontier_attestation=frontier,
        demand_table_agreement=demand_table_agreement,
        relation_membership_attestation=_relation_membership(
            module, plan["enrolledFiles"]
        ),
        runtime_attestation=_runtime_attestation(),
    )


def test_direct_seal_refuses_absent_demand_table_agreement() -> None:
    module = _load()

    body = _direct_seal(module, demand_table_agreement=None)

    _assert_unmeasured_without_width(body)
    assert "demand-table-agreement-absent" in body["unmeasuredReasons"]["plan"]


def test_direct_seal_refuses_malformed_demand_table_agreement() -> None:
    module = _load()

    body = _direct_seal(
        module,
        demand_table_agreement={
            "schema": "demand-table-shard-agreement/v1",
            "allAgree": True,
        },
    )

    _assert_unmeasured_without_width(body)
    assert "demand-table-agreement-malformed" in body["unmeasuredReasons"]["plan"]


def test_direct_seal_refuses_seven_of_eight_demand_table_agreement() -> None:
    module = _load()
    cid = "blake3-512:table-a"
    identity = _demand_identity()
    claim = {"demandTableCid": cid, "demandTableIdentity": identity}

    body = _direct_seal(
        module,
        demand_table_agreement={
            "schema": "demand-table-shard-agreement/v1",
            "plan": claim,
            "shards": {f"s{i:02d}": claim for i in range(7)},
            "authenticatedShardCount": 7,
            "expectedShardCount": 8,
            "allAgree": False,
        },
    )

    _assert_unmeasured_without_width(body)
    assert "demand-table-agreement-incomplete" in body["unmeasuredReasons"]["plan"]


def test_eight_authenticated_shards_seal_one_demand_table_meaning() -> None:
    module = _load()
    cid = "blake3-512:table-a"
    identity = _demand_identity()
    plan = _plan(module, cid=cid, identity=identity)
    assert plan["demandTableCid"] == cid
    assert plan["demandTableIdentity"] == identity
    assert plan["planCid"] == module.canonical_cid(
        {key: value for key, value in plan.items() if key != "planCid"}
    )

    status, body = module.compose_from_partials(
        plan,
        _partials(module, plan, cid=cid, identity=identity),
        runtime_attestation=_runtime_attestation(),
    )

    assert status == "sealed"
    assert body["demandTableCid"] == cid
    assert body["demandTableIdentity"] == identity
    agreement = body["demandTableAgreement"]
    assert agreement["authenticatedShardCount"] == 8
    assert agreement["expectedShardCount"] == 8
    assert agreement["allAgree"] is True
    assert set(agreement["shards"]) == {f"s{i:02d}" for i in range(8)}
    assert body["bodyCid"]


def test_demand_table_meaning_moves_plan_partial_and_body_cids() -> None:
    module = _load()
    left_identity = _demand_identity(suffix="a")
    right_identity = _demand_identity(suffix="b")
    left_plan = _plan(module, cid="blake3-512:table-a", identity=left_identity)
    right_plan = _plan(module, cid="blake3-512:table-b", identity=right_identity)
    assert left_plan["planCid"] != right_plan["planCid"]

    left_partial = _partials(
        module,
        left_plan,
        cid="blake3-512:table-a",
        identity=left_identity,
    )[0]
    right_partial = _partials(
        module,
        right_plan,
        cid="blake3-512:table-b",
        identity=right_identity,
    )[0]
    assert left_partial["partialCid"] != right_partial["partialCid"]

    left_status, left_body = module.compose_from_partials(
        left_plan,
        _partials(
            module,
            left_plan,
            cid="blake3-512:table-a",
            identity=left_identity,
        ),
        runtime_attestation=_runtime_attestation(),
    )
    right_status, right_body = module.compose_from_partials(
        right_plan,
        _partials(
            module,
            right_plan,
            cid="blake3-512:table-b",
            identity=right_identity,
        ),
        runtime_attestation=_runtime_attestation(),
    )
    assert left_status == right_status == "sealed"
    assert left_body["bodyCid"] != right_body["bodyCid"]


def test_one_different_shard_table_refuses_as_mismatch() -> None:
    module = _load()
    cid = "blake3-512:table-a"
    identity = _demand_identity()
    plan = _plan(module, cid=cid, identity=identity)

    status, body = module.compose_from_partials(
        plan,
        _partials(module, plan, cid=cid, identity=identity, lying_index=6),
        runtime_attestation=_runtime_attestation(),
    )

    assert status == "unmeasured"
    _assert_unmeasured_without_width(body)
    assert "demand-table-testimony-mismatch" in body["unmeasuredReasons"]["s06"]


def test_one_absent_shard_table_refuses_differently_from_mismatch() -> None:
    module = _load()
    cid = "blake3-512:table-a"
    identity = _demand_identity()
    plan = _plan(module, cid=cid, identity=identity)

    status, body = module.compose_from_partials(
        plan,
        _partials(module, plan, cid=cid, identity=identity, absent_index=3),
        runtime_attestation=_runtime_attestation(),
    )

    assert status == "unmeasured"
    _assert_unmeasured_without_width(body)
    reason = body["unmeasuredReasons"]["s03"]
    assert "demand-table-testimony-absent" in reason
    assert "demand-table-testimony-mismatch" not in reason


def test_plan_refuses_semantic_identity_with_unrecomputable_content_key() -> None:
    module = _load()
    identity = _demand_identity()
    identity["contentKey"] = "blake3-512:authored-not-recomputed"

    try:
        _plan(module, cid="blake3-512:table-a", identity=identity)
    except ValueError as error:
        assert "demand-table-identity-content-key-mismatch" in str(error)
    else:
        raise AssertionError("plan accepted an unrecomputable semantic identity")


def _relation_membership(module, files):
    """Positive attendance for both relations over the given files.

    Built by hand rather than through the module so the wire shape the mint
    demands is pinned here independently of the code that checks it.
    """
    relations = {}
    for relation in module.RELATION_MEMBERSHIP_RELATIONS:
        members = [
            module.canonical_cid({"relation": relation, "file": file})
            for file in files
        ]
        preimage = {
            "schema": "recensus-relation-member-manifest/v1",
            "relation": relation,
            "memberCids": members,
            "memberCount": len(members),
        }
        manifest = {**preimage, "manifestCid": module.canonical_cid(preimage)}
        relations[relation] = {"expected": manifest, "observed": dict(manifest)}
    return {
        "schema": "recensus-relation-membership-attestation/v1",
        "relations": relations,
        # Required, not optional: an empty list says "no seat was exempt",
        # which is a different fact from a shard that does not report
        # exemptions at all.
        "measurementExhaustedSeats": [],
    }
