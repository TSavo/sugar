from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.idd.proofir_vocab_instruments import (
    collect_naked_formula_boundary_crossings,
    collect_proofir_vocabulary_frontier,
)

ROOT = Path(__file__).resolve().parents[4]


def test_construction_law_scanner_reads_the_live_repo() -> None:
    report = collect_naked_formula_boundary_crossings(ROOT)

    assert report.r > 0
    axes = {crossing.axis for crossing in report.crossings}
    assert "_formula_to_rpc-outside-serializer" in axes
    assert "raw-BodyUniverseDto-formula-slot" in axes
    assert "Formula-typed-node-constructor-field" in axes
    assert "dict-str-any-formula-slot" in axes
    assert "monolithic-proofir-semantic-class" in axes

    assert any(
        crossing.path.endswith("factory/literal_call_report.py")
        and "_formula_to_rpc" in crossing.detail
        for crossing in report.crossings
    )
    assert any(
        crossing.path.endswith("kit_rpc/body_universe_dto.py")
        and crossing.axis == "dict-str-any-formula-slot"
        and "pre" in crossing.detail
        for crossing in report.crossings
    )
    assert any(
        crossing.axis == "Formula-typed-node-constructor-field"
        and "FunctionContract.post" in crossing.detail
        for crossing in report.crossings
    )
    assert any(
        crossing.axis == "monolithic-proofir-semantic-class"
        and "FunctionContract" in crossing.detail
        for crossing in report.crossings
    )
    assert not any(
        crossing.axis == "monolithic-proofir-semantic-class"
        and "EqualityFact" in crossing.detail
        for crossing in report.crossings
    )
    assert not any(
        crossing.path.endswith("idd/proofir_vocab_instruments.py")
        for crossing in report.crossings
    )


def test_construction_law_scanner_is_reported_in_the_frontier_vector() -> None:
    report = collect_proofir_vocabulary_frontier(ROOT)

    assert report.naked_formula_boundary_crossings == report.construction_law.r
    payload = report.to_json()
    assert (
        payload["r"]["naked_formula_boundary_crossings"]
        == report.construction_law.r
    )
