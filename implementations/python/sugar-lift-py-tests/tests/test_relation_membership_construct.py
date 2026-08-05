"""The attendance verdict is a missing constructor, not a guard.

The eight contract teeth in ``test_recensus_relation_membership_seal`` pin what
the mint refuses. They would all stay green if the refusal were an ordinary
``if`` that a new callsite could route around -- which is exactly how the two
sealed frontierWidth=477 receipts were minted with zero lexical-call testimony.

These teeth pin the other half: only the mint can make an attendance verdict,
there are exactly two of them, and the sealed body's membership field has no
source other than a conserved one.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from collections.abc import Mapping

import pytest

from sugar_lift_py_tests.authenticated_pytest import runtime_cid_for_identity
from sugar_lift_py_tests.demand_table_identity import DemandTableIdentityV1
from sugar_lift_py_tests.repo_root import sugar_lift_py_tests_package_root
from sugar_lift_python_source.canonical import cid_of_json

_SCRIPTS = sugar_lift_py_tests_package_root() / "scripts"
_SCRIPT = _SCRIPTS / "compose_control_effect_board.py"


def _load():
    if str(_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS))
    spec = importlib.util.spec_from_file_location(
        "compose_control_effect_board_membership_construct", _SCRIPT
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
        "sysVersion": "3.12.13 relation-membership-construct-test",
        "cacheTag": "cpython-312",
        "SOABI": "cpython-312-x86_64-linux-gnu",
        "hexVersion": "0x30c0df0",
        "platformTag": "Linux-test-x86_64-with-glibc2.39",
        "invokedExecutable": "/venv/bin/python",
        "resolvedBaseExecutable": "/runtime/bin/python3.12",
        "executableSha256": "b" * 64,
    }
    return {
        "requiredRuntime": "cpython-3.12.13",
        "runtimeIdentity": identity,
        "runtimeCid": runtime_cid_for_identity(identity),
    }


def _demand_identity() -> dict[str, object]:
    identity = DemandTableIdentityV1(
        content_key="",
        corpus_manifest_cid="blake3-512:corpus-construct",
        schema_version="python-demand-table/v1",
        producer_source_cid="blake3-512:producer-construct",
        resolution_config_cid="blake3-512:config-construct",
        parser_identity="cpython-3.12",
        file_count=2,
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


def _membership(module, files) -> dict[str, object]:
    """Positive attendance for both relations over the given files."""
    relations: dict[str, object] = {}
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
    }


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


def test_a_third_attendance_variant_cannot_be_declared() -> None:
    """Absent / conserved / refused is not an open set a consumer may extend."""
    module = _load()

    with pytest.raises(TypeError) as error:

        class MostlyConserved(module.RelationMembershipAttestationV1):
            pass

    assert "relation-membership-attestation-variant-not-closed" in str(error.value)


@pytest.mark.parametrize("variant", ("RelationMembershipConservedV1",
                                     "RelationMembershipRefusedV1"))
def test_only_the_mint_may_make_an_attendance_verdict(variant: str) -> None:
    """A new callsite can write a guard; it cannot write this object."""
    module = _load()
    cls = getattr(module, variant)
    kwargs: dict[str, object] = (
        {"wire": {"schema": "x", "relations": {}}}
        if variant == "RelationMembershipConservedV1"
        else {"findings": [("relation-membership-missing", "lexical-call")],
              "detail": "forged"}
    )

    with pytest.raises(TypeError) as error:
        cls(**kwargs)

    assert "relation-membership-attestation-not-mint-minted" in str(error.value)


def test_a_refused_verdict_has_no_conserved_wire() -> None:
    """Absence and lookup-failure never share a representation."""
    module = _load()
    refused = module.authenticate_relation_membership(None)

    assert refused.refusal_reason() is not None
    with pytest.raises(TypeError) as error:
        refused.conserved_wire()
    assert "relation-membership-attestation-refused" in str(error.value)


def test_a_refusal_reason_outside_the_closed_set_is_refused() -> None:
    module = _load()

    with pytest.raises(TypeError) as error:
        module.RelationMembershipRefusedV1(
            findings=[("relation-membership-probably-fine", None)],
            detail="invented",
            _authority=module._RELATION_MEMBERSHIP_AUTHORITY,
        )

    assert "relation-membership-refusal-reason-not-declared" in str(error.value)


def test_sealed_body_membership_field_has_exactly_one_source() -> None:
    """Static tooth: the field is minted from a conserved verdict and nowhere else.

    A second assignment -- a literal, a passthrough of the caller's mapping, a
    ``or {}`` default -- would restore the bypass without failing any behaviour
    tooth, so the source is read directly.
    """
    module = _load()
    tree = ast.parse(_SCRIPT.read_text(encoding="utf-8"))
    seal = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "seal_board_from_aggregate"
    )
    sources = [
        ast.unparse(value)
        for node in ast.walk(seal)
        if isinstance(node, ast.Dict)
        for key, value in zip(node.keys, node.values)
        if isinstance(key, ast.Constant)
        and key.value == "relationMembershipAttestation"
    ]
    assert sources == ["relation_membership.conserved_wire()"], sources
    assert module.RelationMembershipAttestationV1._variants_closed is True


def test_one_shard_with_no_membership_refuses_the_whole_compose() -> None:
    """The historical case at the real door: seven attesting seats cannot cover one silent seat."""
    module = _load()
    files = ["pandas/f0.py", "pandas/f1.py"]
    demand_cid = "blake3-512:table-construct"
    demand_identity = _demand_identity()
    plan = module.build_plan(
        enrolled_files=files,
        shard_count=2,
        measured_commit="098bf65aa",
        aggregate_hash="agg",
        manifest_shape_cid="manifest",
        bins=[[file] for file in files],
        split_mode="fixture",
        prior_hits=0,
        prior_misses=2,
        estimated_loads=[1.0, 1.0],
        demand_table_cid=demand_cid,
        demand_table_identity=demand_identity,
    )
    runtime = _runtime_attestation()
    partials = [
        module.mint_partial(
            plan=plan,
            shard_index=index,
            terminal_rows=[(file, _row(module, file))],
            demand_table_cid=demand_cid,
            demand_table_identity=demand_identity,
            relation_membership_attestation=(
                None if index == 1 else _membership(module, [file])
            ),
            runtime_attestation=runtime,
        )
        for index, file in enumerate(files)
    ]

    # The shard refuses itself first, in its own testimony -- pinned here so
    # this tooth is not satisfied by compose's separate re-read downstream.
    assert partials[0]["measured"] is True
    assert partials[1]["measured"] is False
    assert (
        "relation-membership-attestation-absent"
        in partials[1]["unmeasuredReason"]
    )
    assert "relationMembershipAttestation" not in partials[1]

    status, body = module.compose_from_partials(
        plan, partials, runtime_attestation=runtime
    )

    assert status == "unmeasured"
    assert "frontierWidth" not in body
    assert "bodyCid" not in body
    assert "relation-membership-attestation-absent" in body["unmeasuredReasons"]["s01"]
    assert "s00" not in body["unmeasuredReasons"]


def test_compose_reauthenticates_membership_it_reads_from_a_partial() -> None:
    """A measured partial whose membership was stripped is caught at compose.

    Distinct from the seat above: that one is refused by ``mint_partial``, so
    its reason arrives on the partial's own status. Here the partial is
    ``measured`` and complete, and only compose's own read of the shard's
    membership stands between it and a sealed width.
    """
    module = _load()
    files = ["pandas/f0.py"]
    demand_cid = "blake3-512:table-construct"
    demand_identity = _demand_identity()
    plan = module.build_plan(
        enrolled_files=files,
        shard_count=1,
        measured_commit="098bf65aa",
        aggregate_hash="agg",
        manifest_shape_cid="manifest",
        bins=[files],
        split_mode="fixture",
        prior_hits=0,
        prior_misses=1,
        estimated_loads=[1.0],
        demand_table_cid=demand_cid,
        demand_table_identity=demand_identity,
    )
    runtime = _runtime_attestation()
    partial = module.mint_partial(
        plan=plan,
        shard_index=0,
        terminal_rows=[(files[0], _row(module, files[0]))],
        demand_table_cid=demand_cid,
        demand_table_identity=demand_identity,
        relation_membership_attestation=_membership(module, files),
        runtime_attestation=runtime,
    )
    assert partial["measured"] is True
    del partial["relationMembershipAttestation"]

    status, body = module.compose_from_partials(
        plan, [partial], runtime_attestation=runtime
    )

    assert status == "unmeasured"
    assert "frontierWidth" not in body
    assert "bodyCid" not in body
    assert "relation-membership-attestation-absent" in body["unmeasuredReasons"]["s00"]


def test_two_attesting_shards_seal_the_unioned_population() -> None:
    """Attendance composes: the sealed width names every member both shards saw."""
    module = _load()
    files = ["pandas/f0.py", "pandas/f1.py"]
    demand_cid = "blake3-512:table-construct"
    demand_identity = _demand_identity()
    plan = module.build_plan(
        enrolled_files=files,
        shard_count=2,
        measured_commit="098bf65aa",
        aggregate_hash="agg",
        manifest_shape_cid="manifest",
        bins=[[file] for file in files],
        split_mode="fixture",
        prior_hits=0,
        prior_misses=2,
        estimated_loads=[1.0, 1.0],
        demand_table_cid=demand_cid,
        demand_table_identity=demand_identity,
    )
    runtime = _runtime_attestation()
    partials = [
        module.mint_partial(
            plan=plan,
            shard_index=index,
            terminal_rows=[(file, _row(module, file))],
            demand_table_cid=demand_cid,
            demand_table_identity=demand_identity,
            relation_membership_attestation=_membership(module, [file]),
            runtime_attestation=runtime,
        )
        for index, file in enumerate(files)
    ]

    status, body = module.compose_from_partials(
        plan, partials, runtime_attestation=runtime
    )

    assert status == "sealed", body.get("unmeasuredReasons")
    sealed = body["relationMembershipAttestation"]
    assert isinstance(sealed, Mapping)
    for relation in module.RELATION_MEMBERSHIP_RELATIONS:
        observed = sealed["relations"][relation]["observed"]
        assert observed["memberCount"] == 2
        assert sorted(observed["memberCids"]) == sorted(
            module.canonical_cid({"relation": relation, "file": file})
            for file in files
        )
    assert body["bodyCid"]
