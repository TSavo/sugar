from __future__ import annotations

from pathlib import Path
from collections import Counter

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
    axes = {crossing.axis for crossing in report.crossings}
    assert "_formula_to_rpc-outside-serializer" not in axes
    assert "raw-BodyUniverseDto-formula-slot" not in axes
    assert "dict-str-any-formula-slot" not in axes
    assert "Formula-typed-node-constructor-field" not in axes
    assert "monolithic-proofir-semantic-class" not in axes

    assert not any(crossing.path.endswith("factory/literal_call_report.py") for crossing in report.crossings)
    assert not any(crossing.path.endswith("kit_rpc/body_universe_dto.py") for crossing in report.crossings)
    assert not any("RefusalRecord" in crossing.detail for crossing in report.crossings)
    assert not any("FunctionContract" in crossing.detail for crossing in report.crossings)
    assert not any(
        crossing.axis == "monolithic-proofir-semantic-class"
        and "EqualityFact" in crossing.detail
        for crossing in report.crossings
    )
    assert not any(
        crossing.path.endswith("idd/proofir_vocab_instruments.py")
        for crossing in report.crossings
    )


def test_s8_remaining_vocab_nodes_drain_live_scanner_vector() -> None:
    report = collect_naked_formula_boundary_crossings(ROOT)
    axes = Counter(crossing.axis for crossing in report.crossings)

    assert report.r == 0
    assert axes["_formula_to_rpc-outside-serializer"] == 0
    assert axes["raw-BodyUniverseDto-formula-slot"] == 0
    assert axes["dict-str-any-formula-slot"] == 0
    assert axes["Formula-typed-node-constructor-field"] == 0
    assert axes["monolithic-proofir-semantic-class"] == 0
    assert not any("FunctionContract" in crossing.detail for crossing in report.crossings)
    assert not any("RefusalRecord" in crossing.detail for crossing in report.crossings)


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

    assert report.naked_formula_boundary_crossings == report.construction_law.r
    assert report.unknown_sort_equality_seats == report.unknown_sort_equality.r
    payload = report.to_json()
    assert (
        payload["r"]["naked_formula_boundary_crossings"]
        == report.construction_law.r
    )
    assert (
        payload["r"]["unknown_sort_equality_seats"]
        == report.unknown_sort_equality.r
    )
