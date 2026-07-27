"""Authenticated producer law for pandas' no-call BinOp assertion body."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

import pytest

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_source_tree.nodes import BinOp
from sugar_source_tree.tree import SourceFile

DEMAND_TABLE_CONTENT_KEY = (
    "blake3-512:e225fcd0991f7c9011107521516e513390e448cc78ec4ce2da5eceb7116e1d89"
    "6cba3f8d9f19c1b5375692117a8395aa9f1529a63b768387ce9aeb43d8323499"
)
PANDAS_MANIFEST_CID = (
    "sha256:a223a4499d0909f22190748b4aca9144e35a58fec31e84cb924e2c25fd3c03d0"
)
FILE_SHA256 = "14698f3356d531b1cb87761c57be48737cb547b7ac97f7a6406c16336d5e2f5f"
SOURCE_CID = (
    "blake3-512:bbfb81036cfd42d0473c1d7d2521f9dc10c2518c6cec8897c22a5782c9a53a03"
    "50a4d7f8e9dcea6899b53a879b555503f0138481b50d55351f0b2896c7589ec6"
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _corpus_file() -> Path:
    import pandas

    return Path(pandas.__file__).resolve().parent / "tests/series/test_logical_ops.py"


def _authenticated_demand_row() -> dict:
    with tempfile.TemporaryDirectory() as scratch:
        output = Path(scratch) / "python-demand-table.json"
        pulled = subprocess.run(
            [
                str(_repo_root() / "bin/sugarbin"),
                "artifact",
                "pull",
                "--kind",
                "python-demand-table",
                "--content-key",
                DEMAND_TABLE_CONTENT_KEY,
                "--output",
                str(output),
                "--runtime",
                "cpython-3.14.4",
            ],
            cwd=_repo_root(),
            capture_output=True,
            text=True,
            check=False,
        )
        assert pulled.returncode == 0 and output.is_file(), (
            "the authenticated #6464 demand table is absent; do not rebuild it: "
            + pulled.stderr
        )
        payload = json.loads(output.read_text(encoding="utf-8"))

    assert payload["contentKey"] == DEMAND_TABLE_CONTENT_KEY
    assert payload["authentication"]["authenticatedCorpusManifestCid"] == (
        PANDAS_MANIFEST_CID
    )
    assert payload["authentication"]["pandas"] == "3.0.3"
    assert payload["identity"]["fileCount"] == 1421
    rows = tuple(
        row
        for row in payload["rows"]
        if row.get("kind") == "context-manager-demand"
        and row.get("targetSymbol") == "pytest.raises"
        and row.get("gapKind") is None
        and row.get("useSite")
        == {
            "sourceCid": SOURCE_CID,
            "startLine": 95,
            "startCol": 9,
            "endLine": 98,
            "endCol": 5,
        }
    )
    assert len(rows) == 1
    return rows[0]


def _line_96_bitand(source: str, path: Path):
    source_cid = blake3_512_of(source.encode("utf-8"))
    tree = SourceFile(
        (source, str(path), source_cid),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    matches = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, BinOp)
        and node.op.kind == "BitAnd"
        and node.line_col_span().start_line == 96
    )
    assert len(matches) == 1
    return matches[0]


def _assert_named_undecided_refusal(node, *, observed: str) -> None:
    with pytest.raises(ConstructionPanic) as raised:
        node.sugar().desugar(None)
    info = raised.value.info
    assert info.owner == "binary_operation_exception_floor"
    assert info.observed == observed
    assert "authenticated exceptional exit" in info.requested
    assert "TypeError" not in str(info)
    assert "RuntimeEffect" not in str(info)


def test_pandas_series_nan_bitand_stays_source_undecided_in_the_producer() -> None:
    """Truthful/lying runtime twins cannot license invented source testimony."""
    demand = _authenticated_demand_row()
    path = _corpus_file()
    truthful = path.read_text(encoding="utf-8")
    assert hashlib.sha256(truthful.encode("utf-8")).hexdigest() == FILE_SHA256
    assert demand["useSite"]["startLine"] == 95
    assert truthful.count("s_0123 & np.nan") == 1

    import pandas

    series = pandas.Series(range(4), dtype="int64")
    with pytest.raises(TypeError):
        series & float("nan")
    assert (series & 0).tolist() == [0, 0, 0, 0]

    lying = truthful.replace("s_0123 & np.nan", "s_0123 & 0")
    _assert_named_undecided_refusal(
        _line_96_bitand(truthful, path),
        observed="SymbolicValue & SymbolicValue",
    )
    _assert_named_undecided_refusal(
        _line_96_bitand(lying, path),
        observed="SymbolicValue & TermValue",
    )
