from __future__ import annotations

import importlib.metadata
import json
import subprocess
import tempfile
from functools import cache
from pathlib import Path
from types import MappingProxyType

import pytest

from sugar_lift_py_tests.context_manager_resolution import (
    ContextManagerResolutionGapV1,
    ResolvedContractRefsV1,
    SourceFragmentCoordinateV1,
)
from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
from sugar_lift_python_source.canonical import blake3_512_of

_TABLE_CID = "blake3-512:" + "t" * 128
_CATALOG_CID = "blake3-512:" + "c" * 128
_DEMAND_CID = (
    "blake3-512:6e13b2f2c9e67794d662ff357cf8c0ddc2a1509902c0130bfe1ee63377695a113"
    "b6111d3e44accbd277c993149c8d9f7cabd5f63fc0f3707fc8a49a967abf523"
)
_OPAQUE_DEMAND_CID = (
    "blake3-512:f299951a254712ea1fb53f4f9611aa80c9fe2dd92814cc28b4300540cbc5214d"
    "7cf4b7d11832f7ba113be17d73b79a34d0fb7c4ddc1705ea1bfa272ecfa58c65"
)
_SOURCE_CID = (
    "blake3-512:3a71aa9c523d26a6a541cb6fdc124d37c364245b959d41873619701b421fbe370"
    "7b50d44f9d87083a783b17ec779000a4480863c8dc8435761e6f17238dd3ee0"
)
_DEMAND_TABLE_CONTENT_KEY = (
    "blake3-512:0ce7c645a7525f1fe5189b808162b49d3fc3ba3d898bfb3d5086e0f295b8b8d"
    "263fe7f530a6aa34adb125615a21e69fdee249e0314bf199b8f43580375153ab0"
)
_CORPUS_MANIFEST_CID = (
    "blake3-512:6f317a5a489eb7e730064d79792f0d1656723130603309e2f2ed9cbedb604eda"
    "1c4b77a26dc90c980411292ea3994af9015da4cd850b5a307af5a4998b563530"
)
_EXTERNAL_ERROR_TARGET = "pandas._testing.external_error_raised"


def _install_root() -> Path:
    distribution = importlib.metadata.distribution("pandas")
    package = Path(distribution.locate_file("pandas")).resolve()
    assert package.is_dir()
    return package.parent


@cache
def _external_error_demand_rows() -> tuple[dict, ...]:
    """Consume the authenticated table and retain this exact demand family."""
    root = Path(__file__).resolve().parents[4]
    with tempfile.TemporaryDirectory() as scratch:
        output = Path(scratch) / "demand-table.json"
        completed = subprocess.run(
            [
                str(root / "bin" / "sugarbin"),
                "artifact",
                "pull",
                "--kind",
                "python-demand-table",
                "--content-key",
                _DEMAND_TABLE_CONTENT_KEY,
                "--output",
                str(output),
                "--runtime",
                "cpython-3.12.13",
            ],
            cwd=root,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr
        payload = json.loads(output.read_text(encoding="utf-8"))

    assert payload["contentKey"] == _DEMAND_TABLE_CONTENT_KEY
    assert payload["authentication"]["python"] == "cpython-3.12.13"
    assert (
        payload["authentication"]["authenticatedCorpusManifestCid"]
        == _CORPUS_MANIFEST_CID
    )
    return tuple(
        row
        for row in payload["rows"]
        if row.get("targetSymbol") == _EXTERNAL_ERROR_TARGET
    )


@cache
def _feather_tree():
    """The pandas helper is a named construction refusal, not an assertion.

    The coordinate and CIDs are the exact row consumed from the authenticated
    demand table at content key ``0ce7...53ab0``.  The local import and returned
    ``pytest.raises(..., match=None)`` are behind a dynamic export: construction
    may name that missing preimage, but must not invent it from the With head.
    """
    root = _install_root()
    path = root / "pandas/tests/io/test_feather.py"
    source_cid = blake3_512_of(path.read_bytes())
    assert source_cid == _SOURCE_CID
    external_site = SourceFragmentCoordinateV1(source_cid, 40, 13, 40, 48)
    opaque_site = SourceFragmentCoordinateV1(source_cid, 33, 13, 33, 46)
    external_gap = ContextManagerResolutionGapV1(
        _DEMAND_CID,
        external_site,
        "pandas._testing.external_error_raised",
        "runtime-selected",
        (),
    )
    opaque_gap = ContextManagerResolutionGapV1(
        _OPAQUE_DEMAND_CID,
        opaque_site,
        "pytest.raises",
        "runtime-selected",
        (),
    )
    refs = ResolvedContractRefsV1(
        _CATALOG_CID,
        _TABLE_CID,
        MappingProxyType({external_site: external_gap, opaque_site: opaque_gap}),
    )

    return open_source_file_for_construction(
        path, root=root, contract_refs=refs, populate_derived=True
    )


def test_external_error_raised_follows_return_to_keyword_validation_refusal() -> None:
    """The pandas helper is followed without inventing an assertion boundary.

    The coordinate and CIDs are the exact row consumed from the authenticated
    demand table at content key ``0ce7...53ab0``.  The local import and returned
    ``pytest.raises(..., match=None)`` is followed from source.  Its returned
    manager currently stops in pytest's source-visible keyword-validation branch,
    before semantics exist; neither the With-head spelling nor the helper name
    may bridge that refusal.

    Authenticated CPython 3.12.13 replay at ``b08fdb0b2`` includes
    ``371a4f99c``, ``7329ce546``, ``a3aedc8a5``, and the #6522 BinOp drain.
    None reattributes this coordinate: it remains the exact force-floor below.
    A future FOLLOWS assertion therefore requires a cited production mechanism,
    not a test-only expectation change.
    """
    from sugar_lift_py_tests.context_manager_resolution import (
        ContextManagerResolutionGapV1,
    )
    from sugar_source_tree.panic import ContextManagerResolutionConstructionGap

    tree = _feather_tree()
    with_node = next(
        node
        for node in tree.nodes()
        if node.kind == "With" and node.line_col_span().start_line == 40
    )
    reference = tree.unit.construction_context.source_derived_contract_refs[
        SourceFragmentCoordinateV1(_SOURCE_CID, 40, 13, 40, 48)
    ]
    assert isinstance(reference, ContextManagerResolutionGapV1)
    assert reference.kind == "force-floor"
    assert reference.detail == (
        "binary_operation_exception_floor:SymbolicValue + CallSiteValue"
    )
    with pytest.raises(ContextManagerResolutionConstructionGap) as caught:
        with_node.sugar()
    assert caught.value.kind == "force-floor"
    assert "SymbolicValue + CallSiteValue" in caught.value.observed


def test_external_error_raised_population_is_the_authenticated_47_with_sites() -> None:
    """The stated 51 mentions contain exactly 47 manager-demand sites.

    The remaining mentions are the helper definition, its export, and one call
    assigned to ``ctx``; the fourth non-With mention names the test function
    containing an ordinary With site.  This test consumes the shared demand
    table, so the denominator is manager construction sites rather than text.
    """
    rows = _external_error_demand_rows()
    assert len(rows) == 47
    assert all(row["expectedKind"] == "context-manager-contract" for row in rows)
    assert all(row["gapKind"] is None for row in rows)
    assert any(
        row["useSite"]
        == {
            "sourceCid": _SOURCE_CID,
            "startLine": 40,
            "startCol": 13,
            "endLine": 40,
            "endCol": 48,
        }
        for row in rows
    )


def test_adjacent_computed_class_raises_stays_typed_opaque() -> None:
    """The adjacent direct raises call differs only by its computed operands."""
    from sugar_source_tree.panic import WithConstructionGap, WithConstructionGapKind

    tree = _feather_tree()
    with_node = next(
        node
        for node in tree.nodes()
        if node.kind == "With" and node.line_col_span().start_line == 33
    )

    with pytest.raises(WithConstructionGap) as caught:
        with_node.sugar()

    assert caught.value.coordinate.start_line == 33
    assert caught.value.gap_kind is WithConstructionGapKind.FORCE_FLOOR
    assert "SymbolicValue + CallSiteValue" in caught.value.observed
