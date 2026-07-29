"""RED: module construction receipts authenticate parser-owned Ellipsis."""

from __future__ import annotations

import pytest

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.binding_state import (
    ConstructedValueCategoryGap,
    ConstructionTestimonyReporterV1,
    SubstitutionTraceBuilderV1,
    constructed_value_cid_v2,
)
from sugar_source_tree.reporter import CollectingReporter
from sugar_source_tree.tree import SourceFile


def test_module_receipt_canonicalizes_authenticated_ellipsis_occurrence() -> None:
    source = "def exact(value=...):\n    return value\n"
    source_cid = blake3_512_of(source.encode())
    reporter = ConstructionTestimonyReporterV1(
        CollectingReporter(), SubstitutionTraceBuilderV1(source_cid)
    )

    source_file = SourceFile(
        (source, "ellipsis_receipt.py", source_cid), reporter=reporter
    )

    assert source_file.root.reporter is reporter
    assert source_file.constructed_module.reporting_projection is reporter
    assert (
        source_file.constructed_module.construction_event_receipt_cid
        == source_file.construction_event_receipt_cid
    )
    assert source_file.construction_event_receipt_cid.startswith("blake3-512:")


def test_unrelated_sentinel_does_not_acquire_ellipsis_category() -> None:
    sentinel = object()

    with pytest.raises(
        ConstructedValueCategoryGap,
        match="unclassified constructed value category builtins.object",
    ):
        constructed_value_cid_v2(sentinel)
