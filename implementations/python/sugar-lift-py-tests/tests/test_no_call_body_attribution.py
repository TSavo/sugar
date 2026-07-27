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
    attribute_body_probes,
    discover_no_call_body_probes,
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


def test_named_refusal_is_not_counted_as_a_failure() -> None:
    """Lying twin: refusing honestly must not inflate the failure frontier."""
    report = attribute_body_probes((_probe(ProducerFamily.BINOP, _named_refusal),))

    row = report.by_family[ProducerFamily.BINOP]
    assert row.authenticated_exceptional_exits == 0
    assert row.named_refusals == 1
    assert row.construction_panics == 0
    assert row.failures == 0
    assert report.bodies[0].outcome is AttributionOutcome.NAMED_REFUSAL


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


def test_discovery_uses_shared_demand_coordinates_and_excludes_call_bodies(
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

    rows = []
    for path, source in (
        (subscript_path, subscript_source),
        (call_path, call_source),
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

    probes = discover_no_call_body_probes({"rows": rows}, package)

    assert len(probes) == 1
    assert probes[0].family is ProducerFamily.SUBSCRIPT
    assert probes[0].body_id == "subscript_body.py:3:Subscript"
