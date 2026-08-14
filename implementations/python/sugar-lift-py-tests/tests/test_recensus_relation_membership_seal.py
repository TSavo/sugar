"""A sealed width requires conserved relation-membership testimony.

This contract deliberately precedes the producer manifests governed by #7346
and #7348.  The seal sees opaque member CIDs: it does not choose how lexical
calls or target patterns mint durable source-occurrence identities.  It does
require positive, recomputable expected/observed manifests for both relations.

These teeth remain red until that producer-owned construct exists.  In
particular, the absent arm reproduces the historical casualty: a direct call to
the sole mint currently seals with no relation-membership testimony at all.
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Mapping, Sequence

import pytest

from sugar_lift_py_tests.authenticated_pytest import runtime_cid_for_identity
from sugar_lift_py_tests.demand_table_identity import DemandTableIdentityV1
from sugar_lift_py_tests.repo_root import sugar_lift_py_tests_package_root
from sugar_lift_python_source.canonical import cid_of_json

_SCRIPTS = sugar_lift_py_tests_package_root() / "scripts"
_SCRIPT = _SCRIPTS / "compose_control_effect_board.py"
_RELATIONS = ("lexical-call", "target-pattern")


def _load():
    if str(_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS))
    spec = importlib.util.spec_from_file_location(
        "compose_control_effect_board_relation_membership", _SCRIPT
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
        "sysVersion": "3.12.13 relation-membership-seal-test",
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


def _demand_identity() -> dict[str, object]:
    identity = DemandTableIdentityV1(
        content_key="",
        corpus_manifest_cid="blake3-512:corpus-a",
        schema_version="python-demand-table/v1",
        producer_source_cid="blake3-512:producer-a",
        resolution_config_cid="blake3-512:config-a",
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


def _plan(module, *, demand_cid: str, demand_identity: Mapping[str, object]):
    files = [f"pandas/f{i}.py" for i in range(8)]
    return module.build_plan(
        enrolled_files=files,
        shard_count=8,
        measured_commit="cd866d512d",
        aggregate_hash="agg",
        manifest_shape_cid="manifest",
        bins=[[file] for file in files],
        split_mode="fixture",
        prior_hits=0,
        prior_misses=8,
        estimated_loads=[1.0] * 8,
        demand_table_cid=demand_cid,
        demand_table_identity=demand_identity,
    )


def _demand_table_agreement(
    *, demand_cid: str, demand_identity: Mapping[str, object]
) -> dict[str, object]:
    claim = {
        "demandTableCid": demand_cid,
        "demandTableIdentity": demand_identity,
    }
    return {
        "schema": "demand-table-shard-agreement/v1",
        "plan": claim,
        "shards": {f"s{i:02d}": claim for i in range(8)},
        "authenticatedShardCount": 8,
        "expectedShardCount": 8,
        "allAgree": True,
    }


def _manifest(module, relation: str, member_cids: Sequence[str]) -> dict[str, object]:
    preimage = {
        "schema": "recensus-relation-member-manifest/v1",
        "relation": relation,
        "memberCids": list(member_cids),
        "memberCount": len(member_cids),
    }
    return {**preimage, "manifestCid": module.canonical_cid(preimage)}


def _membership_attestation(
    module,
    *,
    changed_relation: str | None = None,
    mutation: str | None = None,
) -> dict[str, object]:
    relations: dict[str, object] = {}
    for relation in _RELATIONS:
        expected = [
            module.canonical_cid({"relation": relation, "occurrence": index})
            for index in range(2)
        ]
        observed = list(expected)
        if relation == changed_relation:
            if mutation == "missing":
                observed.pop()
            elif mutation == "extra":
                observed.append(
                    module.canonical_cid({"relation": relation, "occurrence": 2})
                )
            elif mutation == "duplicate":
                observed.append(observed[0])
            else:
                raise AssertionError(f"unknown mutation: {mutation}")
        relations[relation] = {
            "expected": _manifest(module, relation, expected),
            "observed": _manifest(module, relation, observed),
        }
    return {
        "schema": "recensus-relation-membership-attestation/v1",
        "relations": relations,
        # Required, not optional: an empty list says "no seat was exempt",
        # which is a different fact from a shard that does not report
        # exemptions at all.
        "measurementExhaustedSeats": [],
    }


def _direct_seal(
    module,
    *,
    relation_membership_attestation: Mapping[str, object] | None,
    omit_membership_argument: bool = False,
) -> dict[str, object]:
    demand_cid = "blake3-512:table-a"
    demand_identity = _demand_identity()
    plan = _plan(module, demand_cid=demand_cid, demand_identity=demand_identity)
    measured_rows = [(file, _row(module, file)) for file in plan["enrolledFiles"]]
    aggregate = module.aggregate_terminal_rows(
        measured_rows,
        enrolled_files=plan["enrolledFiles"],
        manifest_cid="manifest",
    )
    frontier, failures = module.attest_frontier_rows(measured_rows)
    assert failures == []
    kwargs = {
        "plan": plan,
        "per_shard_cids": {f"s{i:02d}": f"partial-{i}" for i in range(8)},
        "compose_cid": "blake3-512:compose",
        "measured_commit": "cd866d512d",
        "frontier_attestation": frontier,
        "demand_table_agreement": _demand_table_agreement(
            demand_cid=demand_cid, demand_identity=demand_identity
        ),
        "runtime_attestation": _runtime_attestation(),
    }
    if not omit_membership_argument:
        kwargs["relation_membership_attestation"] = relation_membership_attestation
    return module.seal_board_from_aggregate(aggregate, **kwargs)


def _assert_unmeasured_without_width(body: Mapping[str, object]) -> None:
    assert body["kind"] == "control-effect-recensus-unmeasured/v1"
    assert body["status"] == "unmeasured"
    assert body["measured"] is False
    assert "frontierWidth" not in body
    assert "bodyCid" not in body


def test_direct_seal_refuses_no_relation_membership_manifest() -> None:
    """Historical casualty: zero relation testimony must never seal again."""
    module = _load()

    body = _direct_seal(
        module,
        relation_membership_attestation=None,
        omit_membership_argument=True,
    )

    _assert_unmeasured_without_width(body)
    assert "relation-membership-attestation-absent" in body["unmeasuredReasons"]["plan"]


@pytest.mark.parametrize("relation", _RELATIONS)
def test_direct_seal_refuses_missing_relation_member(relation: str) -> None:
    module = _load()

    body = _direct_seal(
        module,
        relation_membership_attestation=_membership_attestation(
            module, changed_relation=relation, mutation="missing"
        ),
    )

    _assert_unmeasured_without_width(body)
    assert (
        f"relation-membership-missing:{relation}" in body["unmeasuredReasons"]["plan"]
    )


@pytest.mark.parametrize("relation", _RELATIONS)
def test_direct_seal_refuses_extra_relation_member(relation: str) -> None:
    module = _load()

    body = _direct_seal(
        module,
        relation_membership_attestation=_membership_attestation(
            module, changed_relation=relation, mutation="extra"
        ),
    )

    _assert_unmeasured_without_width(body)
    assert f"relation-membership-extra:{relation}" in body["unmeasuredReasons"]["plan"]


@pytest.mark.parametrize("relation", _RELATIONS)
def test_direct_seal_refuses_duplicate_relation_member(relation: str) -> None:
    module = _load()

    body = _direct_seal(
        module,
        relation_membership_attestation=_membership_attestation(
            module, changed_relation=relation, mutation="duplicate"
        ),
    )

    _assert_unmeasured_without_width(body)
    assert (
        f"relation-membership-duplicate:{relation}" in body["unmeasuredReasons"]["plan"]
    )


def test_exact_relation_membership_agreement_still_seals() -> None:
    module = _load()
    attestation = _membership_attestation(module)

    body = _direct_seal(module, relation_membership_attestation=attestation)

    assert body["status"] == "sealed"
    assert body["measured"] is True
    assert body["frontierWidth"] == 0
    assert body["relationMembershipAttestation"] == attestation
    assert body["bodyCid"]
