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

_TABLE_CID = "blake3-512:" + "t" * 128
_CATALOG_CID = "blake3-512:" + "c" * 128
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
    # Current residual names the exit-face negation on unfloored call state.
    assert reference.kind == "exit-may-halt"
    assert reference.detail == "unary_operation_exception_floor:CallSiteValue not"


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


@cache
def _external_error_attributions():
    """Construct each authenticated demand without entering unrelated managers."""
    from collections import defaultdict

    from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
    from sugar_lift_py_tests.context_manager_resolution import (
        SourceDerivedContextManagerRefV1,
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

            def evaluate(manager=manager, path=path, site=site):
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
            manager_span = manager.items[0].context_expr.line_col_span()
            producer_node = manager.body[0]
            if len(manager.body) == 1 and producer_node.kind == "Expr":
                producer_node = producer_node.value
            producer_span = producer_node.line_col_span()
            attributed.append(
                attribute_body_probe(
                    BodyProbe(
                        body_id=f"{relative}:{site.start_line}",
                        family=producer_node.kind,
                        evaluator=evaluate,
                        consumer_coordinate=(
                            f"{relative}:{manager_span.start_line}:"
                            f"{manager_span.start_col}-{manager_span.end_line}:"
                            f"{manager_span.end_col}"
                        ),
                        producer_coordinate=(
                            f"{relative}:{producer_span.start_line}:"
                            f"{producer_span.start_col}-{producer_span.end_line}:"
                            f"{producer_span.end_col}"
                        ),
                        producer_call_descendants=sum(
                            node.kind == "Call" for node in producer_node.walk()
                        ),
                    )
                )
            )
    return tuple(attributed)


def test_external_error_raised_47_site_outcome_partition() -> None:
    from collections import Counter

    attributions = _external_error_attributions()
    summary = summarize_attribution_outcomes(attributions)

    assert summary.enrolled == 47
    assert summary.authenticated_exceptional_exits == 0
    assert summary.named_refusals == 47
    assert summary.construction_panics == 0
    assert len({body.consumer_coordinate for body in attributions}) == 47
    assert all(body.consumer_coordinate.startswith("tests/") for body in attributions)
    assert all(body.producer_coordinate.startswith("tests/") for body in attributions)
    assert {body.outcome for body in attributions} == {AttributionOutcome.NAMED_REFUSAL}
    rendered = tuple(body.render() for body in attributions)
    assert len(set(rendered)) == 47
    assert all(
        line.startswith("outcome=named-refusal consumer=tests/") for line in rendered
    )
    assert Counter(body.detail for body in attributions) == {
        "With._construct_sugar:authenticated preconstruction resolution gap: "
        "exit-may-halt [unary_operation_exception_floor:CallSiteValue not]": 42,
        "SymbolicValue.attribute:undecided receiver runtime type or member "
        "semantics: SymbolicValue.ArrowInvalid": 4,
        "SymbolicValue.attribute:undecided receiver runtime type or member "
        "semantics: SymbolicValue.ArrowException": 1,
    }


def test_external_error_raised_subscript_seeds_name_both_independent_coordinates():
    """Three source sites expand independently of the returned manager route."""
    by_producer = {
        body.producer_coordinate: body for body in _external_error_attributions()
    }
    expected = {
        "tests/series/accessors/test_list_accessor.py:101:8-101:26": "tests/series/accessors/test_list_accessor.py:100:9-100:50",
        "tests/series/accessors/test_list_accessor.py:133:8-133:20": "tests/series/accessors/test_list_accessor.py:132:9-132:50",
        "tests/series/accessors/test_list_accessor.py:135:8-135:19": "tests/series/accessors/test_list_accessor.py:134:9-134:50",
    }

    assert set(expected) <= set(by_producer)
    for producer_coordinate, consumer_coordinate in expected.items():
        attribution = by_producer[producer_coordinate]
        assert attribution.consumer_coordinate == consumer_coordinate
        assert attribution.family == "Subscript"
        assert attribution.producer_call_descendants == 0


def test_external_error_raised_former_panics_are_now_named_at_concrete_sites() -> None:
    by_id = {body.body_id: body for body in _external_error_attributions()}

    refusal = by_id["tests/io/test_feather.py:40"]
    former_panic = by_id["tests/extension/test_arrow.py:1715"]
    assert refusal.outcome is AttributionOutcome.NAMED_REFUSAL
    assert former_panic.outcome is AttributionOutcome.NAMED_REFUSAL
    assert refusal.consumer_coordinate == "tests/io/test_feather.py:40:13-40:48"
    assert former_panic.consumer_coordinate == (
        "tests/extension/test_arrow.py:1715:9-1715:50"
    )
    assert "exit-may-halt" in refusal.detail
    assert former_panic.detail == (
        "SymbolicValue.attribute:undecided receiver runtime type or member "
        "semantics: SymbolicValue.ArrowInvalid"
    )


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
                    "exit-may-halt:unary_operation_exception_floor:"
                    "CallSiteValue not",
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
