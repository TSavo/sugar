from __future__ import annotations

import pytest

from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.floor import RaiseValue
from sugar_lift_py_tests.ir import str_const
from sugar_lift_py_tests.no_call_body_attribution import (
    CANONICAL_CORPUS_MANIFEST_CID,
    FAMILY_DENOMINATORS,
    HISTORICAL_PATH_SHAPE_DIGEST,
    AttributionOutcome,
    AttributionInvariantError,
    BodyProbe,
    DemandTableRefusal,
    ProducerFamily,
    attribute_body_probe,
    attribute_body_probes,
    discover_no_call_body_probes,
    require_expected_denominators,
    summarize_attribution_outcomes,
    validate_shared_demand_table,
)
from sugar_lift_py_tests.outcome import Complete
from sugar_source_tree.panic import SugarNotWritten


def _probe(family: ProducerFamily, evaluator) -> BodyProbe:
    return BodyProbe(
        body_id=f"pandas/example.py:1:{family.value}",
        family=family,
        evaluator=evaluator,
    )


def _raise_value():
    return Complete(
        RaiseValue(
            RaiseEffect(
                exception_type_coordinate=str_const("TypeError"),
                occurrence="pandas/example.py:1:4",
            )
        )
    )


def _nameless_raise_value():
    return Complete(RaiseValue(RaiseEffect()))


def _call_owned_raise_value():
    return Complete(
        RaiseValue(
            RaiseEffect(
                exception_type_coordinate=str_const("TypeError"),
                occurrence="pandas/example.py:1:4",
                producer_node_owner="Call",
            )
        )
    )


def _named_refusal():
    raise SugarNotWritten(
        blame="test_no_call_body_attribution.py:native-producer",
        owner="native-producer",
        observed="source-visible operands do not decide the failure mode",
        requested="authenticated exceptional exit or retained refusal",
        fix="retain this named refusal without inventing an effect",
    )


def _construction_panic():
    from sugar_lift_py_tests.gap.panic import construction_panic_gap

    construction_panic_gap(
        owner="producer-construction",
        blame="pandas/example.py:1",
        observed="missing native operand construction",
        requested="constructed producer operands",
        fix="construct the missing operand without inventing an effect",
    )


def test_truthful_authenticated_body_is_counted_as_an_exceptional_exit() -> None:
    report = attribute_body_probes((_probe(ProducerFamily.SUBSCRIPT, _raise_value),))

    row = report.by_family[ProducerFamily.SUBSCRIPT]
    assert row.authenticated_exceptional_exits == 1
    assert row.named_refusals == 0
    assert row.construction_panics == 0
    assert report.bodies[0].outcome is AttributionOutcome.AUTHENTICATED_EXIT


def test_authenticated_exit_ledger_projects_both_source_coordinates() -> None:
    report = attribute_body_probes((_probe(ProducerFamily.SUBSCRIPT, _raise_value),))

    assert (
        "authenticatedExceptionalExit body=pandas/example.py:1:Subscript "
        f"exceptionTypeCoordinate={str_const('TypeError')!r} "
        "raiseOccurrence=pandas/example.py:1:4"
    ) in report.render()


def test_nameless_halted_face_stays_loud_in_the_exit_ledger() -> None:
    """Lying twin: a Halted face cannot borrow authenticated identity."""
    report = attribute_body_probes(
        (_probe(ProducerFamily.SUBSCRIPT, _nameless_raise_value),)
    )

    row = report.by_family[ProducerFamily.SUBSCRIPT]
    assert row.authenticated_exceptional_exits == 0
    assert row.named_refusals == 1
    assert report.loud_failure_count == 0
    assert "authenticatedExceptionalExit body=" not in report.render()
    assert "native-operation exception identity unproven" in report.render()


def test_corpus_tally_does_not_count_nameless_halted_faces_as_exits() -> None:
    report = attribute_body_probes(
        tuple(
            _probe(ProducerFamily.COMPARE, _nameless_raise_value)
            for _ in range(503)
        )
    )

    row = report.by_family[ProducerFamily.COMPARE]
    assert row.enrolled == 503
    assert row.authenticated_exceptional_exits == 0
    assert row.named_refusals == 503
    assert row.construction_panics == 0
    assert report.outcome_total == 503
    assert report.loud_failure_count == 0


def test_declared_typed_gap_is_a_named_refusal_not_a_failure() -> None:
    """Lying twin: declared refusal must not inflate the failure frontier."""
    report = attribute_body_probes((_probe(ProducerFamily.BINOP, _named_refusal),))

    row = report.by_family[ProducerFamily.BINOP]
    assert row.authenticated_exceptional_exits == 0
    assert row.named_refusals == 1
    assert row.construction_panics == 0
    assert row.failures == 0
    assert report.bodies[0].outcome is AttributionOutcome.NAMED_REFUSAL


def test_shared_outcome_summary_keeps_refusals_separate_from_panics() -> None:
    bodies = (
        attribute_body_probe(_probe(ProducerFamily.BINOP, _named_refusal)),
        attribute_body_probe(_probe(ProducerFamily.BINOP, _construction_panic)),
        attribute_body_probe(_probe(ProducerFamily.BINOP, _raise_value)),
    )

    summary = summarize_attribution_outcomes(bodies)

    assert summary.enrolled == 3
    assert summary.authenticated_exceptional_exits == 1
    assert summary.named_refusals == 1
    assert summary.construction_panics == 1


def test_report_names_every_refusal_coordinate_and_panic_node_owner() -> None:
    report = attribute_body_probes(
        (
            _probe(ProducerFamily.BINOP, _named_refusal),
            _probe(ProducerFamily.SUBSCRIPT, _construction_panic),
        )
    )

    rendered = report.render()

    assert (
        "namedRefusal body=pandas/example.py:1:BinOp "
        "coordinate=native-producer" in rendered
    )
    assert (
        "constructionPanic body=pandas/example.py:1:Subscript "
        "node=Subscript owner=producer-construction" in rendered
    )
    assert report.construction_panic_count == 1


def test_report_keeps_all_six_families_separate() -> None:
    probes = tuple(_probe(family, _named_refusal) for family in ProducerFamily)
    report = attribute_body_probes(probes)

    assert tuple(report.by_family) == tuple(ProducerFamily)
    assert FAMILY_DENOMINATORS == {
        ProducerFamily.SUBSCRIPT: 392,
        ProducerFamily.BINOP: 367,
        ProducerFamily.COMPARE: 181,
        ProducerFamily.ATTRIBUTE: 53,
        ProducerFamily.UNARYOP: 13,
        ProducerFamily.BOOLOP: 2,
    }
    assert sum(FAMILY_DENOMINATORS.values()) == 1008
    assert [row.family for row in report.rows()] == list(ProducerFamily)


def test_construction_panic_remains_a_separate_loud_axis() -> None:
    report = attribute_body_probes(
        (_probe(ProducerFamily.ATTRIBUTE, _construction_panic),)
    )
    row = report.by_family[ProducerFamily.ATTRIBUTE]
    assert row.authenticated_exceptional_exits == 0
    assert row.named_refusals == 0
    assert row.construction_panics == 1
    assert row.failures == 1
    assert report.bodies[0].outcome is AttributionOutcome.CONSTRUCTION_PANIC


def test_silent_completion_stays_a_separate_loud_discrepancy() -> None:
    report = attribute_body_probes(
        (_probe(ProducerFamily.BOOLOP, lambda: Complete(object())),)
    )

    assert report.by_family[ProducerFamily.BOOLOP].enrolled == 1
    assert report.outcome_total == 0
    assert report.loud_failure_count == 1
    assert len(report.discrepancies) == 1
    assert "completed without" in report.discrepancies[0].detail
    assert (
        "unaccounted body=pandas/example.py:1:BoolOp node=BoolOp "
        "detail=pandas/example.py:1:BoolOp (BoolOp) completed without"
        in report.render()
    )
    assert (
        "FAMILY OUTCOME DISCREPANCY family=BoolOp enrolled=1 "
        "threeOutcomeTotal=0 unaccounted=1" in report.render()
    )
    assert (
        "OUTCOME TOTAL DISCREPANCY enrolled=1 threeOutcomeTotal=0 unaccounted=1"
        in report.render()
    )


def test_construction_panics_are_rendered_with_site_and_failing_node_owner() -> None:
    report = attribute_body_probes(
        (_probe(ProducerFamily.SUBSCRIPT, _construction_panic),)
    )

    assert (
        "constructionPanic body=pandas/example.py:1:Subscript "
        "node=Subscript owner=producer-construction"
    ) in report.render()
    assert report.construction_panic_count == 1


def test_join_collects_construction_panic_and_outcome_discrepancy_before_failing() -> (
    None
):
    """#6540 + #6541: both loud axes survive one report transaction."""
    report = attribute_body_probes(
        (
            _probe(ProducerFamily.SUBSCRIPT, _construction_panic),
            _probe(ProducerFamily.BOOLOP, lambda: Complete(object())),
        )
    )

    assert len(report.bodies) == 1
    assert len(report.discrepancies) == 1
    assert report.construction_panic_count == 1
    assert report.outcome_total == 1
    assert report.loud_failure_count == 2
    assert "constructionPanic body=pandas/example.py:1:Subscript" in report.render()
    assert (
        "OUTCOME TOTAL DISCREPANCY enrolled=2 threeOutcomeTotal=1 unaccounted=1"
        in report.render()
    )


def test_receiver_call_panic_is_owned_by_call_before_subscript_is_reached() -> None:
    """Lying twin: root shape cannot steal a failure from its receiver Call."""
    from sugar_lift_py_tests.gap.panic import construction_panic_gap
    from sugar_lift_py_tests.sugar.subscript_sugar import SubscriptSugar

    class RaisingCall:
        def desugar(self, ctx=None):
            construction_panic_gap(
                owner="Call",
                blame="pandas/example.py:1:receiver",
                observed="receiver call raised before returning a value",
                requested="a completed receiver before Subscript evaluation",
                fix="attribute this failing edge to Call",
            )

    class UnreachedIndex:
        def desugar(self, ctx=None):
            raise AssertionError("Subscript index was evaluated after receiver halt")

    expression = SubscriptSugar(
        receiver=RaisingCall(), index=UnreachedIndex(), site="pandas/example.py:1"
    )
    body = attribute_body_probe(
        BodyProbe(
            body_id="pandas/example.py:1:Subscript",
            family=ProducerFamily.SUBSCRIPT,
            evaluator=expression.desugar,
        )
    )

    assert body.family is ProducerFamily.SUBSCRIPT
    assert body.outcome is AttributionOutcome.CONSTRUCTION_PANIC
    assert body.detail == "Call"


def test_receiver_call_exceptional_exit_is_not_claimed_by_root_subscript() -> None:
    report = attribute_body_probes(
        (_probe(ProducerFamily.SUBSCRIPT, _call_owned_raise_value),)
    )

    body = report.bodies[0]
    assert body.family is ProducerFamily.SUBSCRIPT
    assert body.outcome is AttributionOutcome.AUTHENTICATED_EXIT
    assert body.detail == "Call"


def _table_payload() -> dict:
    return {
        "contentKey": "blake3-512:" + "d" * 128,
        "authentication": {
            "python": "cpython-3.12.13",
            "authenticatedCorpusManifestCid": CANONICAL_CORPUS_MANIFEST_CID,
            "pandas": "3.0.3",
        },
        "identity": {
            "corpusManifestCid": CANONICAL_CORPUS_MANIFEST_CID,
            "fileCount": 1421,
        },
        "rows": [],
    }


def test_shared_table_accepts_only_the_canonical_content_manifest() -> None:
    payload = _table_payload()
    validated = validate_shared_demand_table(
        payload, expected_content_key=payload["contentKey"]
    )
    assert validated is payload

    payload = _table_payload()
    payload["authentication"][
        "authenticatedCorpusManifestCid"
    ] = HISTORICAL_PATH_SHAPE_DIGEST
    payload["identity"]["corpusManifestCid"] = HISTORICAL_PATH_SHAPE_DIGEST
    with pytest.raises(DemandTableRefusal, match="historical path-shape"):
        validate_shared_demand_table(
            payload, expected_content_key=payload["contentKey"]
        )


def test_discovery_classifies_the_body_root_and_excludes_root_calls(
    tmp_path,
) -> None:
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_source_tree.nodes import With
    from sugar_source_tree.tree import SourceFile

    package = tmp_path / "pandas"
    package.mkdir()
    subscript_path = package / "subscript_body.py"
    subscript_source = (
        "def f(values):\n" "    with boundary(TypeError):\n" "        values[2]\n"
    )
    subscript_path.write_text(subscript_source, encoding="utf-8")
    call_path = package / "call_body.py"
    call_source = "def g():\n    with boundary(TypeError):\n        opaque()\n"
    call_path.write_text(call_source, encoding="utf-8")
    binop_path = package / "binop_body.py"
    binop_source = (
        "def h():\n" "    with boundary(TypeError):\n" "        opaque() + 1\n"
    )
    binop_path.write_text(binop_source, encoding="utf-8")

    rows = []
    for path, source in (
        (subscript_path, subscript_source),
        (call_path, call_source),
        (binop_path, binop_source),
    ):
        source_cid = blake3_512_of(source.encode())
        tree = SourceFile(
            (source, str(path), source_cid),
            construction_context=TreeConstructionContextV1.for_source_call_construction(),
        )
        node = next(item for item in tree.nodes() if isinstance(item, With))
        span = node.items[0].context_expr.line_col_span()
        rows.append(
            {
                "kind": "context-manager-demand",
                "gapKind": None,
                "targetSymbol": (
                    "native.boundary" if path == binop_path else "pytest.raises"
                ),
                "useSite": {
                    "sourceCid": source_cid,
                    "startLine": span.start_line,
                    "startCol": span.start_col,
                    "endLine": span.end_line,
                    "endCol": span.end_col,
                },
            }
        )

    probes = discover_no_call_body_probes({"rows": rows}, package)

    assert [(probe.family, probe.body_id) for probe in probes] == [
        (ProducerFamily.BINOP, "binop_body.py:3:BinOp"),
        (ProducerFamily.SUBSCRIPT, "subscript_body.py:3:Subscript"),
    ]

    binop_only = discover_no_call_body_probes(
        {"rows": rows}, package, families=frozenset({ProducerFamily.BINOP})
    )
    assert [(probe.family, probe.body_id) for probe in binop_only] == [
        (ProducerFamily.BINOP, "binop_body.py:3:BinOp")
    ]


def test_population_selection_never_reads_manager_target_symbol() -> None:
    """All resolved managers enroll; manager spelling grants no membership."""
    assert "targetSymbol" not in discover_no_call_body_probes.__code__.co_consts


def test_discovery_projects_one_family_without_constructing_peer_sources(
    tmp_path, monkeypatch
) -> None:
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_source_tree.nodes import With
    from sugar_source_tree.tree import SourceFile

    package = tmp_path / "pandas"
    package.mkdir()
    sources = {
        "attribute_body.py": (
            "def f(series):\n"
            "    with boundary(AttributeError):\n"
            "        series.bad\n"
        ),
        "subscript_body.py": (
            "def g(value):\n    with boundary(IndexError):\n        value[2]\n"
        ),
    }
    rows = []
    subscript_cid = None
    for filename, source in sources.items():
        path = package / filename
        path.write_text(source, encoding="utf-8")
        source_cid = blake3_512_of(source.encode())
        if filename == "subscript_body.py":
            subscript_cid = source_cid
        tree = SourceFile(
            (source, str(path), source_cid),
            construction_context=TreeConstructionContextV1.for_source_call_construction(),
        )
        node = next(item for item in tree.nodes() if isinstance(item, With))
        span = node.items[0].context_expr.line_col_span()
        rows.append(
            {
                "kind": "context-manager-demand",
                "gapKind": None,
                "targetSymbol": "pytest.raises",
                "useSite": {
                    "sourceCid": source_cid,
                    "startLine": span.start_line,
                    "startCol": span.start_col,
                    "endLine": span.end_line,
                    "endCol": span.end_col,
                },
            }
        )

    original = SourceFile.__init__

    def refuse_peer_construction(self, source, *args, **kwargs):
        if source[2] == subscript_cid:
            raise AssertionError("peer producer source was constructed")
        return original(self, source, *args, **kwargs)

    monkeypatch.setattr(SourceFile, "__init__", refuse_peer_construction)
    probes = discover_no_call_body_probes(
        {"rows": rows}, package, families=frozenset({ProducerFamily.ATTRIBUTE})
    )

    assert [probe.body_id for probe in probes] == ["attribute_body.py:3:Attribute"]


def test_selected_family_denominator_remains_fixed() -> None:
    probes = tuple(
        _probe(ProducerFamily.ATTRIBUTE, _named_refusal)
        for _ in range(FAMILY_DENOMINATORS[ProducerFamily.ATTRIBUTE])
    )
    assert (
        require_expected_denominators(
            probes, families=frozenset({ProducerFamily.ATTRIBUTE})
        )
        == probes
    )

    with pytest.raises(AttributionInvariantError, match="inventory differs"):
        require_expected_denominators(
            probes[:-1], families=frozenset({ProducerFamily.ATTRIBUTE})
        )


def test_attribute_family_denominator_is_native_root_inventory() -> None:
    assert FAMILY_DENOMINATORS[ProducerFamily.ATTRIBUTE] == 53
