from __future__ import annotations

import pytest

from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.floor import RaiseValue
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
    return Complete(RaiseValue(RaiseEffect(exception_name="TypeError")))


def _named_refusal():
    raise SugarNotWritten(
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


def test_escaped_construction_panic_remains_a_separate_loud_axis() -> None:
    report = attribute_body_probes(
        (_probe(ProducerFamily.ATTRIBUTE, _construction_panic),)
    )
    row = report.by_family[ProducerFamily.ATTRIBUTE]
    assert row.authenticated_exceptional_exits == 0
    assert row.named_refusals == 0
    assert row.construction_panics == 1
    assert row.failures == 1
    assert report.bodies[0].outcome is AttributionOutcome.CONSTRUCTION_PANIC


def test_silent_completion_is_not_a_fourth_outcome() -> None:
    with pytest.raises(AttributionInvariantError, match="completed without"):
        attribute_body_probes(
            (_probe(ProducerFamily.BOOLOP, lambda: Complete(object())),)
        )


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
            "def f():\n    with boundary(AttributeError):\n        factory().bad\n"
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
                "targetSymbol": (
                    "authenticated.boundary"
                    if filename == "attribute_body.py"
                    else "authenticated.resource"
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
