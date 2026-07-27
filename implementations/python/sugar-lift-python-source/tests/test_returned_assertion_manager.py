"""Authenticated returned-manager classification in the pinned pandas corpus.

``pandas._testing.external_error_raised`` is a thin factory:

    def external_error_raised(expected_exception):
        import pytest
        return pytest.raises(expected_exception, match=None)

Authority is the local import plus the returned manager's native shape — never
the helper spelling and never a With-head invent. The lying twin in
``test_sole_path_manager_construction`` keeps an ordinary resource under the
same spelling out of EffectBoundary.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from functools import cache
from pathlib import Path

import pytest

from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
from sugar_lift_py_tests.context_manager_resolution import (
    ContextManagerResolutionGapV1,
    SourceDerivedContextManagerRefV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction


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
    """Populate derived manager refs for the pinned feather use site."""
    corpus = authenticated_pandas_corpus()
    assert (corpus.version, corpus.file_count) == ("3.0.3", 1421)
    path = corpus.root / "tests/io/test_feather.py"
    return open_source_file_for_construction(
        path,
        root=corpus.root.parent,
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
        populate_derived=True,
    )


def _with_at(line: int):
    return next(
        node
        for node in _feather_tree().nodes()
        if node.kind == "With" and node.line_col_span().start_line == line
    )


def test_external_error_raised_follows_authenticated_returned_manager() -> None:
    """Truthful: local import plus returned manager supplies the classification.

    Construction follows the factory return into the installed RaisesExc dual-
    mode body. Full EffectBoundary summary derivation still stops at the
    exit-face residual (expected_exceptions / matches floor); that residual is
    named and stage-keyed, never bridged by the helper spelling.
    """
    from sugar_lift_py_tests.context_manager_contract import (
        EffectBoundarySemanticsV1,
        NoMessagePatternV1,
    )
    from sugar_lift_py_tests.sugar.with_effect_boundary_sugar import (
        WithEffectBoundarySugar,
    )

    with_node = _with_at(40)
    reference = with_node._prebound_manager_resolution(with_node.items[0])

    if isinstance(reference, SourceDerivedContextManagerRefV1):
        assert isinstance(reference.semantics, EffectBoundarySemanticsV1)
        # ``match=None`` is written, constructed, and classified as no pattern.
        assert isinstance(reference.semantics.message_pattern, NoMessagePatternV1)
        assert isinstance(with_node.sugar(), WithEffectBoundarySugar)
        return

    # Stage-keyed residual after dual-mode return follow-through. The returned
    # manager constructed; summary derivation has not sealed EffectBoundary yet.
    assert isinstance(reference, ContextManagerResolutionGapV1), reference
    assert reference.kind in {
        "exit-may-halt",
        "enter-may-halt",
        "force-floor",
        "incomplete-call-actuals",
        "no-derived-contract",
    }, reference
    assert "external_error_raised" not in (reference.detail or "")
    # Prior dead-end at dual-mode factory construction is drained.
    assert "binary_operation_exception_floor:SymbolicValue + CallSiteValue" not in (
        reference.detail or ""
    )
    assert "SymbolicValue + CallSiteValue" not in (reference.detail or "")
    # Current residual names the exit-face comparison on unfloored field state.
    assert reference.kind == "exit-may-halt"
    assert "comparison_operation_exception_floor" in (reference.detail or "")


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
    """Lying twin: an unfollowable computed class cannot borrow sibling proof."""
    from sugar_source_tree.panic import WithConstructionGap, WithConstructionGapKind

    with_node = _with_at(33)
    with pytest.raises(WithConstructionGap) as caught:
        with_node.sugar()

    assert caught.value.coordinate.start_line == 33
    assert caught.value.gap_kind is WithConstructionGapKind.FORCE_FLOOR
    # Computed class operand stays stage-keyed force-floor; it must not borrow
    # EffectBoundary authority from the adjacent external_error_raised site.
    observed = caught.value.observed
    assert "force-floor" in observed or "binary_operation_exception_floor" in observed
    assert "EffectBoundary" not in observed
