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
from types import MappingProxyType

import pytest

from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
from sugar_lift_py_tests.context_manager_resolution import (
    ContextManagerResolutionGapV1,
    ResolvedContractRefsV1,
    SourceDerivedContextManagerRefV1,
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
from sugar_lift_py_tests.no_call_body_attribution import (
    AttributionOutcome,
    BodyProbe,
    attribute_body_probe,
    summarize_attribution_outcomes,
)
from sugar_lift_python_source.canonical import blake3_512_of

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
_CATALOG_CID = "blake3-512:" + "c" * 128
_TABLE_CID = "blake3-512:" + "d" * 128
_ARROW_EXCEPTION_SITES = (
    ("tests/series/accessors/test_list_accessor.py", 100, "ArrowInvalid"),
    ("tests/series/accessors/test_list_accessor.py", 132, "ArrowInvalid"),
    ("tests/series/accessors/test_list_accessor.py", 134, "ArrowInvalid"),
    ("tests/extension/test_arrow.py", 1715, "ArrowInvalid"),
    ("tests/io/test_parquet.py", 799, "ArrowException"),
)


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
    # manager constructed through isinstance/tuple/len field flooring; summary
    # derivation still stops at the matches() UnaryOp gate on CallSiteValue.
    assert isinstance(reference, ContextManagerResolutionGapV1), reference
    assert reference.kind in {
        "exit-may-halt",
        "enter-may-halt",
        "force-floor",
        "incomplete-call-actuals",
        "no-derived-contract",
        "method-construction",
    }, reference
    assert "external_error_raised" not in (reference.detail or "")
    # Prior dead-ends drained by returned-manager construction machinery.
    assert "binary_operation_exception_floor:SymbolicValue + CallSiteValue" not in (
        reference.detail or ""
    )
    assert "SymbolicValue + CallSiteValue" not in (reference.detail or "")
    assert "comparison_operation_exception_floor" not in (reference.detail or "")
    # expected_exceptions floors to TupleValue; residual is matches() truth.
    assert reference.kind == "exit-may-halt"
    assert "unary_operation_exception_floor:CallSiteValue not" in (
        reference.detail or ""
    )


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


def test_arrow_exception_sites_are_the_five_authenticated_attribute_operands() -> None:
    """Pin the real source coordinates without turning spellings into dispatch."""
    from sugar_lift_python_source.source_oracle import path_source
    from sugar_source_tree.tree import SourceFile

    corpus = authenticated_pandas_corpus()
    observed = []
    for relative, line, attribute in _ARROW_EXCEPTION_SITES:
        path = corpus.root / relative
        tree = SourceFile(path_source(str(path)))
        matches = [
            node
            for node in tree.nodes()
            if node.kind == "Attribute"
            and node.attr == attribute
            and node.line_col_span().start_line == line
        ]
        assert len(matches) == 1, (relative, line, attribute)
        observed.append((relative, line, attribute))
    assert tuple(observed) == _ARROW_EXCEPTION_SITES


@cache
def _external_error_attributions():
    """Construct each authenticated demand without entering unrelated managers."""
    from collections import defaultdict

    from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
    from sugar_lift_py_tests.context_manager_resolution import (
        ContextManagerResolutionGapV1,
        SourceDerivedContextManagerRefV1,
        SourceFragmentCoordinateV1,
        TreeConstructionContextV1,
    )
    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        reduce_block_to_exitset,
    )
    from sugar_lift_python_source.manager_summary_derivation import (
        populate_source_derived_resource_refs,
    )
    from sugar_lift_python_source.resolution_session import SourceResolutionSession
    from sugar_source_tree.nodes import With
    from sugar_source_tree.tree import SourceFile, SourceTree

    corpus = authenticated_pandas_corpus()
    rows = _external_error_demand_rows()
    paths = {
        blake3_512_of(path.read_bytes()): path
        for path in SourceTree(corpus.root).paths()
    }
    by_source = defaultdict(list)
    for row in rows:
        by_source[row["useSite"]["sourceCid"]].append(row)

    graph_cache = {}
    session = SourceResolutionSession()
    attributed = []
    for source_cid, selected_rows in sorted(by_source.items()):
        path = paths[source_cid]
        refs = {}
        for row in selected_rows:
            site = SourceFragmentCoordinateV1.decode(row["useSite"])
            refs[site] = ContextManagerResolutionGapV1(
                row["authenticatedImportUse"]["cid"],
                site,
                row["targetSymbol"],
                row.get("gapKind") or "runtime-selected",
                (),
            )
        context = TreeConstructionContextV1(
            ResolvedContractRefsV1(_CATALOG_CID, _TABLE_CID, MappingProxyType(refs)),
            workspace_root=str(corpus.root.parent),
        )
        tree = SourceFile(
            (path.read_text(encoding="utf-8"), str(path), source_cid),
            construction_context=context,
        )
        for row in selected_rows:
            site = SourceFragmentCoordinateV1.decode(row["useSite"])
            manager = next(
                node
                for node in tree.nodes()
                if isinstance(node, With)
                and any(
                    item._manager_use_site_span()
                    == (
                        site.start_line,
                        site.start_col,
                        site.end_line,
                        site.end_col,
                    )
                    for item in node.items
                )
            )

            def evaluate(
                manager=manager, path=path, site=site, tree=tree, context=context
            ):
                populate_source_derived_resource_refs(
                    tree,
                    root=corpus.root.parent,
                    path=path,
                    artifact_graph_cache=graph_cache,
                    session=session,
                    selected_coordinates=frozenset({site}),
                )
                reference = context.source_derived_contract_refs.get(site)
                if isinstance(reference, ContextManagerResolutionGapV1):
                    return manager.sugar().desugar()
                assert isinstance(reference, SourceDerivedContextManagerRefV1)
                boundary = manager.sugar()
                return reduce_block_to_exitset(boundary.body, None)

            relative = path.relative_to(corpus.root).as_posix()
            attributed.append(
                attribute_body_probe(
                    BodyProbe(
                        body_id=f"{relative}:{site.start_line}",
                        family="ReturnedManager",
                        evaluator=evaluate,
                    )
                )
            )
    return tuple(attributed)


def test_external_error_raised_47_site_outcome_partition() -> None:
    summary = summarize_attribution_outcomes(_external_error_attributions())

    assert summary.enrolled == 47
    # ArrowInvalid/ArrowException heads construct through import-bound export
    # coordinates; residual is named (exit-face), never ConstructionPanic on
    # SymbolicValue.attribute for the exception-type operand.
    assert summary.construction_panics == 0
    assert summary.authenticated_exceptional_exits > 0
    assert (
        summary.authenticated_exceptional_exits + summary.named_refusals
        == summary.enrolled
    )


def test_external_error_raised_refusal_and_gap_twins_are_concrete_sites() -> None:
    by_id = {body.body_id: body for body in _external_error_attributions()}

    refusal = by_id["tests/io/test_feather.py:40"]
    assert refusal.outcome is AttributionOutcome.NAMED_REFUSAL
    assert refusal.detail == "With._construct_sugar"

    for relative, line, _attribute in _ARROW_EXCEPTION_SITES:
        site = by_id[f"{relative}:{line}"]
        # Before: a named refusal after sealing the attribute spelling. After:
        # provider-defined class testimony reaches the boundary and the real
        # body effect is authenticated.
        assert site.outcome is AttributionOutcome.AUTHENTICATED_EXIT, site


def test_external_error_raised_emits_complete_consumer_testimony() -> None:
    from sugar_lift_py_tests.consumer_resolution_report import (
        CallerAttribution,
        CallerReportTestimony,
        ConsumerHitReport,
    )
    from sugar_lift_py_tests.source_provenance import source_stamp_for_sugar_cli

    source_stamp = source_stamp_for_sugar_cli()
    assert source_stamp is not None
    report = ConsumerHitReport(
        source_stamp=source_stamp,
        runtime="cpython-3.12.13",
        corpus_manifest_cid=_CORPUS_MANIFEST_CID,
        demand_table_content_key=_DEMAND_TABLE_CONTENT_KEY,
        caller=CallerReportTestimony(
            concrete_source_site="pandas/tests/io/test_feather.py:40:13",
            before_outcome="context-manager-demand:resolved-import",
            after_outcome="named-refusal",
            surviving=(
                CallerAttribution(
                    AttributionOutcome.NAMED_REFUSAL,
                    "force-floor:binary_operation_exception_floor:"
                    "SymbolicValue + CallSiteValue",
                ),
            ),
        ),
    )

    assert len(report.lines()) == 8
    assert report.lines()[4].endswith("pandas/tests/io/test_feather.py:40:13")
    assert report.lines()[-1].startswith("survivingTypedGapsOrReattributions reported")


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
