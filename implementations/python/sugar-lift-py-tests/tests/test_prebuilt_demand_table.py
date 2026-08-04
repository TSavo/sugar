"""Prebuilt provisional demand table: zero walks + corpus pin refuse.

Counting walks is a unit test, not a measurement. No stopwatch.
"""

from __future__ import annotations

import sys
import json
from pathlib import Path

import pytest

from sugar_lift_py_tests import lift_rpc as lr
from sugar_lift_py_tests.prebuilt_demand_table import (
    DemandTableArtifactRefusal,
    DemandTablePinMismatch,
    PlanDemandTableRefusal,
    install_prebuilt_demand_table,
    load_plan_bound_demand_table,
    load_prebuilt_demand_table,
    mint_prebuilt_demand_table,
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
    assert first.content_cid == first.to_json_dict()["contentCid"]
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
    assert (
        caught.value.observed_semantic_identity
        == table.semantic_identity.as_dict()
    )
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


def test_load_refuses_tampered_content_cid(tmp_path: Path) -> None:
    corpus = _tiny_corpus(tmp_path / "c")
    artifact = tmp_path / "table.json"
    lr.clear_provisional_contract_refs_memo()
    table = mint_prebuilt_demand_table(_authenticated(corpus))
    write_prebuilt_demand_table(table, artifact)
    raw = artifact.read_text(encoding="utf-8")
    # Flip one hex nibble in the presented contentCid.
    bad = raw.replace(table.content_cid[-4:], "ffff", 1)
    artifact.write_text(bad, encoding="utf-8")
    with pytest.raises(DemandTableArtifactRefusal, match="contentCid mismatch"):
        load_prebuilt_demand_table(artifact, expected_corpus_pin=_expected_pin(corpus))


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
