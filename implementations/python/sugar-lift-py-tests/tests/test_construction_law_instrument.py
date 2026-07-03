from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.idd.proofir_vocab_instruments import (
    collect_naked_formula_boundary_crossings,
    collect_proofir_vocabulary_frontier,
    count_unknown_sort_equality_seats,
)
from sugar_lift_py_tests.proofir import (
    CallTerm,
    ConstTerm,
    ConstructionSite,
    Derived,
    EqualityFact,
    IntSort,
    Provenance,
    UnknownSort,
)

ROOT = Path(__file__).resolve().parents[4]


def test_construction_law_scanner_reads_the_live_repo() -> None:
    report = collect_naked_formula_boundary_crossings(ROOT)

    assert report.r == 0
    assert report.crossings == []

    instrument_source = (
        ROOT
        / "implementations"
        / "python"
        / "sugar-lift-py-tests"
        / "src"
        / "sugar_lift_py_tests"
        / "idd"
        / "proofir_vocab_instruments.py"
    ).read_text(encoding="utf-8")
    assert "_ConstructionLawScanner" not in instrument_source
    assert "_formula_to_rpc-outside-serializer" not in instrument_source
    assert "raw-BodyUniverseDto-formula-slot" not in instrument_source
    assert "dict-str-any-formula-slot" not in instrument_source
    assert "Formula-typed-node-constructor-field" not in instrument_source
    assert "monolithic-proofir-semantic-class" not in instrument_source


def test_s8_remaining_vocab_nodes_drain_live_scanner_vector() -> None:
    report = collect_naked_formula_boundary_crossings(ROOT)

    assert report.r == 0
    assert report.crossings == []


def test_s6_euf_fact_seat_does_not_infer_call_sort_from_rhs() -> None:
    source = (
        ROOT
        / "implementations"
        / "python"
        / "sugar-lift-py-tests"
        / "src"
        / "sugar_lift_py_tests"
        / "factory"
        / "literal_call_report.py"
    ).read_text(encoding="utf-8")

    assert "sort=rhs_term.sort" not in source
    assert "UnknownSort" in source
    assert "call_return_sort" in source


def test_unknown_sort_equality_seat_counter_names_residue() -> None:
    site = ConstructionSite(path="tests/test_construction_law_instrument.py", line=1)
    fact = EqualityFact(
        call_term=CallTerm(
            "opaque",
            (),
            sort=UnknownSort(
                reason="no function-contract return sort available for call:opaque"
            ),
        ),
        rhs_term=ConstTerm(0, sort=IntSort()),
        provenance=Provenance(
            node_class=EqualityFact.node_class,
            construction_site=site,
            warrant=Derived(floor_chain=("test",)),
        ),
    )

    report = count_unknown_sort_equality_seats([fact])

    assert report.r == 1
    assert report.seats[0].callee == "opaque"
    assert "function-contract return sort" in report.seats[0].reason


def test_construction_law_scanner_is_reported_in_the_frontier_vector() -> None:
    report = collect_proofir_vocabulary_frontier(ROOT)

    assert report.construction_law.r == 0
    assert report.unknown_sort_equality_seats == report.unknown_sort_equality.r
    payload = report.to_json()
    assert "naked_formula_boundary_crossings" not in payload["r"]
    assert (
        payload["r"]["unknown_sort_equality_seats"]
        == report.unknown_sort_equality.r
    )
