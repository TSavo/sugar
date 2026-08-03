"""Direct teeth for the Slice 3 worker demand-table entrance."""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import _supervised_enum_worker as worker
from sugar_lift_py_tests.authenticated_pytest import authenticate_corpus
from sugar_lift_py_tests.no_call_body_attribution import SHARED_DEMAND_TABLE_CONTENT_KEY
from sugar_lift_py_tests.prebuilt_demand_table import (
    DemandTableArtifactRefusal,
    mint_prebuilt_demand_table,
    write_prebuilt_demand_table,
)


def _fixture(tmp_path: Path):
    root = tmp_path / "corpus"
    root.mkdir()
    (root / "one.py").write_text("def one():\n    return 1\n", encoding="utf-8")
    (root.parent / "corpus.identity.json").write_text(
        json.dumps({"distribution": "tiny-corpus", "version": "0.0.1"}),
        encoding="utf-8",
    )
    handle = authenticate_corpus(root)
    table = mint_prebuilt_demand_table(handle)
    return root, handle, table


def test_worker_accepts_current_table_and_reaches_context(tmp_path: Path, monkeypatch):
    root, handle, table = _fixture(tmp_path)
    artifact = write_prebuilt_demand_table(table, tmp_path / "table.json")
    monkeypatch.setattr(
        "sugar_lift_py_tests.authenticated_pytest.authenticated_pandas_corpus",
        lambda: handle,
    )
    worker._CONSTRUCTION_CONTEXT = None
    worker._CORPUS_ROOT = None
    result = worker._initialize(str(root), str(artifact), allow_local_demand_derivation=False)
    assert result["kind"] == "context-ready"
    assert result["demand_table_identity"] == table.semantic_identity.content_key


def test_worker_refuses_legacy_key_by_name(tmp_path: Path, monkeypatch):
    root, handle, table = _fixture(tmp_path)
    legacy_identity = dataclasses.replace(
        table.semantic_identity, content_key=SHARED_DEMAND_TABLE_CONTENT_KEY
    )
    legacy = dataclasses.replace(table, semantic_identity=legacy_identity)
    artifact = write_prebuilt_demand_table(legacy, tmp_path / "legacy.json")
    monkeypatch.setattr(
        "sugar_lift_py_tests.authenticated_pytest.authenticated_pandas_corpus",
        lambda: handle,
    )
    worker._CONSTRUCTION_CONTEXT = None
    worker._CORPUS_ROOT = None
    with pytest.raises(DemandTableArtifactRefusal, match="legacy shared demand table identity refused"):
        worker._initialize(str(root), str(artifact), allow_local_demand_derivation=False)
