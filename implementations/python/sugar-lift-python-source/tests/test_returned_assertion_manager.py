from __future__ import annotations

import importlib.metadata
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


def _install_root() -> Path:
    distribution = importlib.metadata.distribution("pandas")
    package = Path(distribution.locate_file("pandas")).resolve()
    assert package.is_dir()
    return package.parent


@cache
def _feather_tree():
    """The pandas helper is a named construction refusal, not an assertion.

    The coordinate and CIDs are the exact row consumed from the authenticated
    demand table at content key ``e225...3499``.  The local import and returned
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


def test_external_error_raised_follows_return_to_named_formal_refusal() -> None:
    """The pandas helper is followed without inventing an assertion boundary.

    The coordinate and CIDs are the exact row consumed from the authenticated
    demand table at content key ``e225...3499``.  The local import and returned
    ``pytest.raises(..., match=None)`` is followed from source.  Its returned
    manager currently stops at an unspecialized formal, before semantics exist;
    neither the With-head spelling nor the helper name may bridge that refusal.
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
        "BindingCoordinateRefSugar.desugar:unspecialized source-call formal"
    )
    with pytest.raises(ContextManagerResolutionConstructionGap) as caught:
        with_node.sugar()
    assert caught.value.kind == "force-floor"
    assert "unspecialized source-call formal" in caught.value.observed


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
    assert "ExitSet with 4 arms" in caught.value.observed
