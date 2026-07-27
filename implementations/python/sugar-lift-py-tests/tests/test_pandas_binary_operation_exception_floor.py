"""Authenticated producer law for pandas' no-call BinOp assertion body."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_source_tree.nodes import BinOp
from sugar_source_tree.tree import SourceFile

PANDAS_MANIFEST_CID = (
    "sha256:a223a4499d0909f22190748b4aca9144e35a58fec31e84cb924e2c25fd3c03d0"
)
FILE_SHA256 = "14698f3356d531b1cb87761c57be48737cb547b7ac97f7a6406c16336d5e2f5f"
def _corpus_file() -> Path:
    corpus = authenticated_pandas_corpus()
    assert (corpus.version, corpus.manifest_cid, corpus.file_count) == (
        "3.0.3",
        PANDAS_MANIFEST_CID,
        1421,
    )
    return corpus.root / "tests/series/test_logical_ops.py"


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
    path = _corpus_file()
    truthful = path.read_text(encoding="utf-8")
    assert hashlib.sha256(truthful.encode("utf-8")).hexdigest() == FILE_SHA256
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
