"""L3d: With item construction — absent or gap row panics named.

One door: ``With._prebound_manager_resolution`` / ``_raise_resolution_gap``.

Checked first: SoftUnresolvedWithSugar is already deleted from production With
(not an uncalled path). After taxonomy purge, gap rows fell to bare
``SugarNotWritten`` — restore the single named
``ContextManagerResolutionConstructionGap`` door (no kind vocabulary).
"""

from __future__ import annotations

from types import MappingProxyType

import pytest

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_py_tests.context_manager_resolution import (
    ContextManagerResolutionGapV1,
    ResolvedContractRefsV1,
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
    _hash_json,
)
from sugar_source_tree.panic import ContextManagerResolutionConstructionGap
from sugar_source_tree.tree import SourceFile


def _cid(fill: str) -> str:
    return "blake3-512:" + (fill * 128)[:128]


def _coord_of_with_manager(sf: SourceFile) -> SourceFragmentCoordinateV1:
    with_node = next(n for n in sf.nodes() if n.kind == "With")
    item = with_node.items[0]
    start_line, start_col, end_line, end_col = item._manager_use_site_span()
    return SourceFragmentCoordinateV1(
        sf.unit.source_cid, start_line, start_col, end_line, end_col
    )


def test_absent_contract_panics_named_with_door():
    """No table row: ContextManagerResolutionConstructionGap, owner With."""
    src = (
        "import contextlib\n"
        "def A(z):\n"
        "    with contextlib.nullcontext():\n"
        "        z = z\n"
        "    return z\n"
    )
    refs = ResolvedContractRefsV1(_cid("c"), _cid("t"), MappingProxyType({}))
    sf = SourceFile(
        (src, "l3d_absent.py", blake3_512_of(src.encode())),
        construction_context=TreeConstructionContextV1(refs),
    )
    with pytest.raises(ContextManagerResolutionConstructionGap) as caught:
        next(sf.functions()).sugar()
    panic = caught.value
    assert panic.owner == "With._construct_sugar"
    assert "derivation" in panic.observed or "coordinate" in panic.observed
    assert "ContextManagerContractRefV1" in panic.requested
    assert "With constructs only through the require door" in panic.fix


def test_gap_row_panics_with_manager_symbol_and_kind_detail():
    """Gap row in table: named panic carries target_symbol and kind detail."""
    src = (
        "import contextlib\n"
        "def A(z):\n"
        "    with contextlib.nullcontext():\n"
        "        z = z\n"
        "    return z\n"
    )
    bare = SourceFile((src, "l3d_gap.py", blake3_512_of(src.encode())))
    site = _coord_of_with_manager(bare)
    preimage = {
        "useSite": {
            "sourceCid": site.source_cid,
            "startLine": site.start_line,
            "startCol": site.start_col,
            "endLine": site.end_line,
            "endCol": site.end_col,
        },
        "targetSymbol": "contextlib.nullcontext",
    }
    gap = ContextManagerResolutionGapV1(
        _hash_json(preimage),
        site,
        "contextlib.nullcontext",
        "runtime-selected",
        (),
    )
    refs = ResolvedContractRefsV1(_cid("c"), _cid("t"), MappingProxyType({site: gap}))
    sf = SourceFile(
        (src, "l3d_gap.py", blake3_512_of(src.encode())),
        construction_context=TreeConstructionContextV1(refs),
    )
    with pytest.raises(ContextManagerResolutionConstructionGap) as caught:
        next(sf.functions()).sugar()
    panic = caught.value
    assert type(panic).__name__ == "ContextManagerResolutionConstructionGap"
    assert panic.owner == "With._construct_sugar"
    assert panic.kind == "runtime-selected"
    assert panic.target_symbol == "contextlib.nullcontext"
    assert "nullcontext" in panic.observed
