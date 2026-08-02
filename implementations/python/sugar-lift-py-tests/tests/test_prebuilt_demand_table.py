"""Prebuilt provisional demand table: zero walks + corpus pin refuse.

Counting walks is a unit test, not a measurement. No stopwatch.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from sugar_lift_py_tests import lift_rpc as lr
from sugar_lift_py_tests.prebuilt_demand_table import (
    DemandTableArtifactRefusal,
    DemandTablePinMismatch,
    install_prebuilt_demand_table,
    load_prebuilt_demand_table,
    mint_prebuilt_demand_table,
    write_prebuilt_demand_table,
)

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

_PIN = {
    "distribution": "tiny-corpus",
    "version": "0.0.1",
    "fileCount": 2,
    "aggregateHash": "sha256:" + ("ab" * 32),
}


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
    return root


def test_mint_content_cid_stable_for_same_rows(tmp_path: Path) -> None:
    corpus = _tiny_corpus(tmp_path / "c1")
    lr.clear_provisional_contract_refs_memo()
    lr.reset_preconstruction_walk_count()
    first = mint_prebuilt_demand_table(corpus, corpus_pin=_PIN)
    lr.clear_provisional_contract_refs_memo()
    second = mint_prebuilt_demand_table(corpus, corpus_pin=_PIN)
    assert first.content_cid == second.content_cid
    assert first.content_cid.startswith("blake3-512:")
    assert lr.preconstruction_walk_count() == 2  # two mints = two walks


def test_cold_process_with_prebuilt_table_performs_zero_corpus_walks(
    tmp_path: Path,
) -> None:
    """THE tooth: load + install + measure must not re-walk the corpus."""
    corpus = _tiny_corpus(tmp_path / "c")
    artifact = tmp_path / "table.json"
    lr.clear_provisional_contract_refs_memo()
    lr.reset_preconstruction_walk_count()
    table = mint_prebuilt_demand_table(corpus, corpus_pin=_PIN)
    write_prebuilt_demand_table(table, artifact)
    walks_at_mint = lr.preconstruction_walk_count()
    assert walks_at_mint == 1

    # Cold process simulation: clear memo + walk counter (new process).
    lr.clear_provisional_contract_refs_memo()
    lr.reset_preconstruction_walk_count()
    assert lr.preconstruction_walk_count() == 0

    loaded = load_prebuilt_demand_table(artifact, expected_corpus_pin=_PIN)
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
    table = mint_prebuilt_demand_table(corpus, corpus_pin=_PIN)
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
    table = mint_prebuilt_demand_table(corpus, corpus_pin=_PIN)
    write_prebuilt_demand_table(table, artifact)
    raw = artifact.read_text(encoding="utf-8")
    # Flip one hex nibble in the presented contentCid.
    bad = raw.replace(table.content_cid[-4:], "ffff", 1)
    artifact.write_text(bad, encoding="utf-8")
    with pytest.raises(DemandTableArtifactRefusal, match="contentCid mismatch"):
        load_prebuilt_demand_table(artifact, expected_corpus_pin=_PIN)


def test_load_refuses_plan_cid_mismatch(tmp_path: Path) -> None:
    corpus = _tiny_corpus(tmp_path / "c")
    artifact = tmp_path / "table.json"
    lr.clear_provisional_contract_refs_memo()
    table = mint_prebuilt_demand_table(corpus, corpus_pin=_PIN)
    write_prebuilt_demand_table(table, artifact)
    with pytest.raises(DemandTableArtifactRefusal, match="plan demandTableCid"):
        load_prebuilt_demand_table(
            artifact,
            expected_corpus_pin=_PIN,
            expected_content_cid="blake3-512:" + ("0" * 128),
        )


def test_install_without_walk_seeds_memo(tmp_path: Path) -> None:
    corpus = _tiny_corpus(tmp_path / "c")
    lr.clear_provisional_contract_refs_memo()
    lr.reset_preconstruction_walk_count()
    table = mint_prebuilt_demand_table(corpus, corpus_pin=_PIN)
    walks = lr.preconstruction_walk_count()
    lr.clear_provisional_contract_refs_memo()
    lr.reset_preconstruction_walk_count()
    install_prebuilt_demand_table(table, root=corpus)
    assert lr.preconstruction_walk_count() == 0
    # Second call to from_demands uses memo — still zero walks.
    lr.provisional_contract_refs_from_demands(corpus)
    assert lr.preconstruction_walk_count() == 0
    assert walks == 1
