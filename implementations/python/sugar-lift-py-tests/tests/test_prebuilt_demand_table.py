"""Prebuilt provisional demand table: zero walks + corpus pin refuse.

Counting walks is a unit test, not a measurement. No stopwatch.
"""

from __future__ import annotations

import os
import shutil
import sys
import json
from pathlib import Path

import pytest

from dataclasses import replace

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_py_tests import lift_rpc as lr
from sugar_lift_py_tests.prebuilt_demand_table import (
    DemandTableArtifactRefusal,
    DemandTablePinMismatch,
    PlanDemandTableRefusal,
    install_prebuilt_demand_table,
    load_plan_bound_demand_table,
    load_prebuilt_demand_table,
    mint_prebuilt_demand_table,
    publish_prebuilt_demand_table,
    validate_prebuilt_demand_table,
    DemandTableSemanticIdentityMismatch,
    write_prebuilt_demand_table,
)
from sugar_lift_py_tests.authenticated_pytest import AuthenticatedPandasCorpus
from sugar_lift_py_tests.authenticated_pytest import authenticate_corpus
from sugar_lift_py_tests.corpus_pin import pin_corpus
from sugar_lift_py_tests.repo_root import sugar_lift_py_tests_package_root

_SCRIPTS = sugar_lift_py_tests_package_root() / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _tiny_corpus(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "a.py").write_text("x = 1\n", encoding="utf-8")
    (root / "b.py").write_text(
        "from contextlib import contextmanager\n"
        "@contextmanager\n"
        "def cm():\n"
        "    yield\n"
        "def f():\n"
        "    with cm():\n"
        "        pass\n",
        encoding="utf-8",
    )
    (root.parent / f"{root.name}.identity.json").write_text(
        json.dumps({"distribution": "tiny-corpus", "version": "0.0.1"}),
        encoding="utf-8",
    )
    return root


def _authenticated(corpus: Path) -> AuthenticatedPandasCorpus:
    return authenticate_corpus(corpus)


def _expected_pin(corpus: Path) -> dict[str, object]:
    handle = _authenticated(corpus)
    return {
        "distribution": handle.distribution,
        "version": handle.version,
        "fileCount": handle.file_count,
        "aggregateHash": handle.manifest_cid,
    }


def test_authentication_preserves_fixture_manifest_and_count(tmp_path: Path) -> None:
    corpus = _tiny_corpus(tmp_path / "c")
    before = pin_corpus(corpus, distribution="tiny-corpus", version="0.0.1")
    after = _authenticated(corpus)
    assert after.manifest_cid == before.aggregate_hash
    assert after.file_count == before.file_count == 2


def test_generic_authentication_refuses_pandas_sidecar(tmp_path: Path) -> None:
    corpus = _tiny_corpus(tmp_path / "c")
    (corpus.parent / f"{corpus.name}.identity.json").write_text(
        json.dumps({"distribution": "pandas", "version": "3.0.3"}),
        encoding="utf-8",
    )
    with pytest.raises(Exception, match="refuses pandas"):
        authenticate_corpus(corpus)


def test_mint_content_cid_stable_for_same_rows(tmp_path: Path) -> None:
    corpus = _tiny_corpus(tmp_path / "c1")
    lr.clear_provisional_contract_refs_memo()
    lr.reset_preconstruction_walk_count()
    first = mint_prebuilt_demand_table(_authenticated(corpus))
    lr.clear_provisional_contract_refs_memo()
    second = mint_prebuilt_demand_table(_authenticated(corpus))
    assert first.content_cid == second.content_cid
    assert first.content_cid.startswith("blake3-512:")
    assert lr.preconstruction_walk_count() == 2  # two mints = two walks


def test_mint_carries_distinct_storage_and_semantic_identities(tmp_path: Path) -> None:
    first_corpus = _tiny_corpus(tmp_path / "first")
    second_corpus = _tiny_corpus(tmp_path / "second")
    (second_corpus / "b.py").write_text(
        "def different():\n    return 2\n", encoding="utf-8"
    )
    first = mint_prebuilt_demand_table(_authenticated(first_corpus))
    second = mint_prebuilt_demand_table(_authenticated(second_corpus))
    assert first.semantic_identity.content_key != second.semantic_identity.content_key
    assert first.content_cid != second.content_cid
    assert first.content_cid == blake3_512_of(first.artifact_bytes())
    assert first.semantic_identity.as_dict()["contentKey"] != first.content_cid


def test_validator_accepts_current_table(tmp_path: Path) -> None:
    corpus = _tiny_corpus(tmp_path / "c")
    handle = _authenticated(corpus)
    table = mint_prebuilt_demand_table(handle)
    validate_prebuilt_demand_table(table, handle)


def test_validator_refuses_table_for_different_corpus(tmp_path: Path) -> None:
    corpus = _tiny_corpus(tmp_path / "c")
    other = _tiny_corpus(tmp_path / "other")
    (other / "b.py").write_text("def different():\n    return 2\n", encoding="utf-8")
    table = mint_prebuilt_demand_table(_authenticated(corpus))
    with pytest.raises(
        DemandTableSemanticIdentityMismatch, match="semantic identity mismatch"
    ):
        validate_prebuilt_demand_table(table, _authenticated(other))


def test_plan_bound_load_missing_artifact_never_derives_locally(tmp_path: Path) -> None:
    corpus = _tiny_corpus(tmp_path / "c")
    handle = _authenticated(corpus)
    identity = mint_prebuilt_demand_table(handle).semantic_identity.as_dict()
    lr.reset_preconstruction_walk_count()

    with pytest.raises(
        DemandTableArtifactRefusal, match="plan-demand-table-artifact-unavailable"
    ):
        load_plan_bound_demand_table(
            tmp_path / "missing.json",
            corpus=handle,
            expected_content_cid="blake3-512:plan-table",
            expected_semantic_identity=identity,
        )

    assert lr.preconstruction_walk_count() == 0


def test_plan_bound_load_cid_mismatch_never_derives_replacement(tmp_path: Path) -> None:
    corpus = _tiny_corpus(tmp_path / "c")
    handle = _authenticated(corpus)
    table = mint_prebuilt_demand_table(handle)
    path = write_prebuilt_demand_table(table, tmp_path / "table.json")
    walks_before = lr.preconstruction_walk_count()

    with pytest.raises(
        PlanDemandTableRefusal, match="plan-demand-table-cid-mismatch"
    ) as caught:
        load_plan_bound_demand_table(
            path,
            corpus=handle,
            expected_content_cid="blake3-512:different-table",
            expected_semantic_identity=table.semantic_identity.as_dict(),
        )

    assert caught.value.observed_content_cid == table.content_cid
    assert caught.value.observed_semantic_identity == table.semantic_identity.as_dict()
    assert lr.preconstruction_walk_count() == walks_before


def test_cold_process_with_prebuilt_table_performs_zero_corpus_walks(
    tmp_path: Path,
) -> None:
    """THE tooth: load + install + measure must not re-walk the corpus."""
    corpus = _tiny_corpus(tmp_path / "c")
    artifact = tmp_path / "table.json"
    lr.clear_provisional_contract_refs_memo()
    lr.reset_preconstruction_walk_count()
    table = mint_prebuilt_demand_table(_authenticated(corpus))
    write_prebuilt_demand_table(table, artifact)
    walks_at_mint = lr.preconstruction_walk_count()
    assert walks_at_mint == 1

    # Cold process simulation: clear memo + walk counter (new process).
    lr.clear_provisional_contract_refs_memo()
    lr.reset_preconstruction_walk_count()
    assert lr.preconstruction_walk_count() == 0

    loaded = load_prebuilt_demand_table(
        artifact, expected_corpus_pin=_expected_pin(corpus)
    )
    assert loaded.content_cid == table.content_cid
    refs = install_prebuilt_demand_table(loaded, root=corpus)
    assert lr.preconstruction_walk_count() == 0

    # D2 path: provisional_contract_refs_from_demands must hit memo, no walk.
    got = lr.provisional_contract_refs_from_demands(corpus)
    assert got is refs
    assert lr.preconstruction_walk_count() == 0

    # measure_file_via_enumerate with contract_refs also zero walks.
    from recensus_enumerate_consumer import measure_file_via_enumerate

    row = measure_file_via_enumerate(
        workspace_root=corpus,
        file_rel="b.py",
        contract_refs=refs,
        distribution="tiny-corpus",
        source_workspace_root=corpus,
    )
    assert isinstance(row, dict)
    assert "category" in row
    assert lr.preconstruction_walk_count() == 0, (
        f"cold process with prebuilt table walked the corpus "
        f"{lr.preconstruction_walk_count()} times; want 0"
    )


def test_load_refuses_corpus_pin_mismatch(tmp_path: Path) -> None:
    """Blonde law: table for the wrong pandas is not a table."""
    corpus = _tiny_corpus(tmp_path / "c")
    artifact = tmp_path / "table.json"
    lr.clear_provisional_contract_refs_memo()
    table = mint_prebuilt_demand_table(_authenticated(corpus))
    write_prebuilt_demand_table(table, artifact)

    wrong = {
        "distribution": "pandas",
        "version": "2.3.3",
        "fileCount": 1415,
        "aggregateHash": "sha256:" + ("cd" * 32),
    }
    with pytest.raises(DemandTablePinMismatch, match="corpus pin mismatch"):
        load_prebuilt_demand_table(artifact, expected_corpus_pin=wrong)


def test_load_refuses_tampered_bytes_by_plan_address(tmp_path: Path) -> None:
    corpus = _tiny_corpus(tmp_path / "c")
    artifact = tmp_path / "table.json"
    lr.clear_provisional_contract_refs_memo()
    table = mint_prebuilt_demand_table(_authenticated(corpus))
    write_prebuilt_demand_table(table, artifact)
    raw = artifact.read_bytes()
    # Tamper one row payload. The address is h(bytes), so the tampered file
    # simply is not the plan's artifact.
    bad = raw.replace(b'"rows":[', b'"rows":[  ', 1)
    assert bad != raw
    artifact.write_bytes(bad)
    with pytest.raises(
        DemandTableArtifactRefusal, match="not the canonical serialization"
    ):
        load_prebuilt_demand_table(artifact, expected_corpus_pin=_expected_pin(corpus))


def test_load_refuses_body_carrying_its_own_content_cid(tmp_path: Path) -> None:
    """The old self-describing spelling is the CAS lie; refuse it by shape."""
    corpus = _tiny_corpus(tmp_path / "c")
    artifact = tmp_path / "table.json"
    lr.clear_provisional_contract_refs_memo()
    table = mint_prebuilt_demand_table(_authenticated(corpus))
    write_prebuilt_demand_table(table, artifact)
    body = json.loads(artifact.read_text(encoding="utf-8"))
    body["contentCid"] = table.content_cid
    artifact.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", "utf-8")
    with pytest.raises(DemandTableArtifactRefusal, match="carries its own contentCid"):
        load_prebuilt_demand_table(artifact, expected_corpus_pin=_expected_pin(corpus))


def test_written_bytes_hash_to_the_published_content_key(tmp_path: Path) -> None:
    """The storage bytes ARE the CAS preimage: h(file) == the claimed key."""
    corpus = _tiny_corpus(tmp_path / "c")
    artifact = tmp_path / "table.json"
    lr.clear_provisional_contract_refs_memo()
    table = mint_prebuilt_demand_table(_authenticated(corpus))
    write_prebuilt_demand_table(table, artifact)
    assert blake3_512_of(artifact.read_bytes()) == table.content_cid


def test_write_refuses_a_key_that_is_not_h_of_the_payload(tmp_path: Path) -> None:
    corpus = _tiny_corpus(tmp_path / "c")
    lr.clear_provisional_contract_refs_memo()
    table = mint_prebuilt_demand_table(_authenticated(corpus))
    lying = replace(table, content_cid="blake3-512:" + ("0" * 128))
    with pytest.raises(
        DemandTableArtifactRefusal, match="storage key/payload mismatch"
    ):
        write_prebuilt_demand_table(lying, tmp_path / "lying.json")


def test_load_refuses_plan_cid_mismatch(tmp_path: Path) -> None:
    corpus = _tiny_corpus(tmp_path / "c")
    artifact = tmp_path / "table.json"
    lr.clear_provisional_contract_refs_memo()
    table = mint_prebuilt_demand_table(_authenticated(corpus))
    write_prebuilt_demand_table(table, artifact)
    with pytest.raises(DemandTableArtifactRefusal, match="plan demandTableCid"):
        load_prebuilt_demand_table(
            artifact,
            expected_corpus_pin=_expected_pin(corpus),
            expected_content_cid="blake3-512:" + ("0" * 128),
        )


def test_install_without_walk_seeds_memo(tmp_path: Path) -> None:
    corpus = _tiny_corpus(tmp_path / "c")
    lr.clear_provisional_contract_refs_memo()
    lr.reset_preconstruction_walk_count()
    table = mint_prebuilt_demand_table(_authenticated(corpus))
    walks = lr.preconstruction_walk_count()
    lr.clear_provisional_contract_refs_memo()
    lr.reset_preconstruction_walk_count()
    install_prebuilt_demand_table(table, root=corpus)
    assert lr.preconstruction_walk_count() == 0
    # Second call to from_demands uses memo — still zero walks.
    lr.provisional_contract_refs_from_demands(corpus)
    assert lr.preconstruction_walk_count() == 0
    assert walks == 1


def _sugarbin_shelf_env(shelf: Path) -> dict[str, str]:
    """Isolate CAS publication to a throwaway shelf; never the real one."""
    env = dict(os.environ)
    env["SUGAR_BINARY_SHELF_ROOT"] = str(shelf)
    env["SUGAR_BINARY_PUBLISH"] = "1"
    return env


@pytest.mark.skipif(
    shutil.which("b3sum") is None, reason="b3sum required for CAS content keys"
)
def test_publish_door_accepts_the_minted_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The entrance plan_control_effect_recensus_shards.py uses, end to end.

    mint -> write -> publish through the real bin/sugarbin. This is the call
    that refused in Actions run 30979536949 with
    crime=cas-publish-key-payload-mismatch.
    """
    corpus = _tiny_corpus(tmp_path / "c")
    artifact = tmp_path / "python-demand-table.json"
    shelf = tmp_path / "shelf"
    lr.clear_provisional_contract_refs_memo()
    for key, value in _sugarbin_shelf_env(shelf).items():
        monkeypatch.setenv(key, value)
    table = mint_prebuilt_demand_table(_authenticated(corpus))
    write_prebuilt_demand_table(table, artifact)
    publish_prebuilt_demand_table(table, artifact)
    # A green publish that filed nothing is a no-op wearing success. Require
    # the cell, and require it to be addressed by h(payload).
    cells = sorted(shelf.rglob("*.metadata.json"))
    assert len(cells) == 1, cells
    key_path_form = table.content_cid.replace("blake3-512:", "blake3-512_")
    assert key_path_form in str(cells[0]), cells[0]


@pytest.mark.skipif(
    shutil.which("b3sum") is None, reason="b3sum required for CAS content keys"
)
def test_publish_door_refuses_a_key_that_is_not_h_of_the_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mismatched claim refuses BY NAME at the CAS door. Do not weaken this."""
    corpus = _tiny_corpus(tmp_path / "c")
    artifact = tmp_path / "python-demand-table.json"
    lr.clear_provisional_contract_refs_memo()
    for key, value in _sugarbin_shelf_env(tmp_path / "shelf").items():
        monkeypatch.setenv(key, value)
    table = mint_prebuilt_demand_table(_authenticated(corpus))
    write_prebuilt_demand_table(table, artifact)
    lying = replace(table, content_cid="blake3-512:" + ("0" * 128))
    with pytest.raises(DemandTableArtifactRefusal) as caught:
        publish_prebuilt_demand_table(lying, artifact)
    assert "crime=cas-publish-key-payload-mismatch" in str(caught.value)
