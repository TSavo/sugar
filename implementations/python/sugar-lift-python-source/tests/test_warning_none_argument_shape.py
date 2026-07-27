"""Pinned real-site testimony for the inverted completed-warning boundary."""

from __future__ import annotations

import hashlib
from pathlib import Path

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.nodes import Call, Constant, With
from sugar_source_tree.tree import SourceFile

# Content manifest (relative path + per-file BLAKE3-512) is identity.
# Path-shape sha256:a223… is historical negative testimony only — never identity.
CONTENT_MANIFEST_CID = (
    "blake3-512:6f317a5a489eb7e730064d79792f0d1656723130603309e2f2ed9cbedb604eda1"
    "c4b77a26dc90c980411292ea3994af9015da4cd850b5a307af5a4998b563530"
)
HISTORICAL_PATH_SHAPE_DIGEST = (
    "sha256:a223a4499d0909f22190748b4aca9144e35a58fec31e84cb924e2c25fd3c03d0"
)
FILE_SHA256 = "ef0819d48825f4614ec088f25b4d342a8808a12b1c5d45cff3281b481ec13252"


def _corpus_file() -> Path:
    corpus = authenticated_pandas_corpus()
    assert (corpus.version, corpus.manifest_cid, corpus.file_count) == (
        "3.0.3",
        CONTENT_MANIFEST_CID,
        1421,
    )
    assert corpus.manifest_cid != HISTORICAL_PATH_SHAPE_DIGEST
    return corpus.root / "tests/series/test_constructors.py"


def test_real_pandas_back_to_back_none_warning_managers_are_distinct_native_sites():
    path = _corpus_file()
    source = path.read_text(encoding="utf-8")
    assert hashlib.sha256(source.encode("utf-8")).hexdigest() == FILE_SHA256
    source_cid = blake3_512_of(source.encode("utf-8"))
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (source, str(path), source_cid),
        construction_context=context,
    )

    sites = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, With) and node.line_col_span().start_line in {1290, 1296}
    )
    assert len(sites) == 2
    assert tuple(len(site.body) for site in sites) == (2, 1)
    for site in sites:
        manager = site.items[0].context_expr
        assert isinstance(manager, Call)
        assert len(manager.args) == 1
        assert isinstance(manager.args[0], Constant)
        assert manager.args[0].value is None

    first_names = tuple(
        node.id
        for statement in sites[0].body
        for node in statement.walk()
        if node.kind == "Name"
    )
    assert first_names.count("middle") == 2

    assert tuple(
        (site.line_col_span().start_line, site.line_col_span().start_col)
        for site in sites
    ) == ((1290, 8), (1296, 8))
    assert tuple(
        (
            site.items[0].context_expr.line_col_span().start_line,
            site.items[0].context_expr.line_col_span().start_col,
        )
        for site in sites
    ) == ((1290, 13), (1296, 13))
