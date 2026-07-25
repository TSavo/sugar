"""WithConstructionGapKind must accept every preconstruction resolution kind.

Census defect (d94f67a31 control-effect): 780/1415 files aborted as
``backend-defect`` with::

    ValueError: 'dynamic-export' is not a valid WithConstructionGapKind

That is instrument crash, not residual silence. Export-resolution kinds ride the
same table into ``ContextManagerResolutionConstructionGap``; the enum must
parse them without ValueError, and unknown future kinds must stay loud as
typed gaps rather than kill the file.
"""

from __future__ import annotations

from sugar_source_tree.panic import (
    ContextManagerResolutionConstructionGap,
    WithConstructionGapKind,
)


def test_dynamic_export_is_a_named_with_construction_gap_kind():
    panic = ContextManagerResolutionConstructionGap(
        kind="dynamic-export",
        demand_cid="demand:test",
        candidate_member_cids=(),
        owner="With._construct_sugar",
        observed="authenticated preconstruction resolution gap: dynamic-export",
        requested="one resolved authenticated ContextManagerContractRefV1",
        fix="publish or resolve the exact typed CM contract before construction",
    )
    assert panic.kind == "dynamic-export"
    assert panic.gap_kind is WithConstructionGapKind.DYNAMIC_EXPORT
    assert panic.resolution_kind == "dynamic-export"


def test_static_export_absent_and_unsupported_statement_parse():
    for kind in ("static-export-absent", "unsupported-statement"):
        panic = ContextManagerResolutionConstructionGap(
            kind=kind,
            demand_cid="demand:test",
            candidate_member_cids=(),
            owner="test",
            observed=kind,
            requested="resolved CM",
            fix="fix",
        )
        assert panic.kind == kind


def test_unknown_resolution_kind_stays_loud_not_valueerror():
    """A newly minted kind must not crash the census with ValueError."""
    panic = ContextManagerResolutionConstructionGap(
        kind="brand-new-resolution-kind-2026",
        demand_cid="demand:test",
        candidate_member_cids=(),
        owner="test",
        observed="new kind",
        requested="resolved CM",
        fix="fix",
    )
    assert panic.gap_kind is WithConstructionGapKind.UNRECOGNIZED_RESOLUTION_KIND
    assert panic.kind == "brand-new-resolution-kind-2026"
    assert panic.resolution_kind == "brand-new-resolution-kind-2026"


def test_known_runtime_selected_still_parses():
    panic = ContextManagerResolutionConstructionGap(
        kind="runtime-selected",
        demand_cid="demand:test",
        candidate_member_cids=(),
        owner="test",
        observed="runtime-selected",
        requested="resolved CM",
        fix="fix",
    )
    assert panic.kind == "runtime-selected"
    assert panic.gap_kind is WithConstructionGapKind.RUNTIME_SELECTED
