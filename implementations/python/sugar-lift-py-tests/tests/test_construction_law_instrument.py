from __future__ import annotations

import pytest

from sugar_lift_py_tests.gap.panic import ConstructionPanic
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

from sugar_lift_py_tests.repo_root import resolve_repo_root

ROOT = resolve_repo_root()


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


def _unknown_sort_call(callee: str) -> CallTerm:
    return CallTerm(
        callee,
        (),
        sort=UnknownSort(
            reason=f"no function-contract return sort available for call:{callee}"
        ),
    )


def _provenance() -> Provenance:
    return Provenance(
        node_class=EqualityFact.node_class,
        construction_site=ConstructionSite(
            path="tests/test_construction_law_instrument.py", line=1
        ),
        warrant=Derived(floor_chain=("test",)),
    )


def test_an_unknown_sort_call_never_equals_an_int_without_a_coercion() -> None:
    """``Eq`` takes terms of one sort: a call whose return sort is unknown is
    never equated with an ``Int`` constant as if its sort were decided.  The
    construction is refused by name, never built over a sort it does not
    have."""
    with pytest.raises(ConstructionPanic, match="matching sorts for Eq"):
        EqualityFact(
            call_term=_unknown_sort_call("opaque"),
            rhs_term=ConstTerm(0, sort=IntSort()),
            provenance=_provenance(),
        )


def test_unknown_sort_equality_seat_counter_names_residue() -> None:
    # An equality the sort law admits: both sides of the one unknown sort.
    fact = EqualityFact(
        call_term=_unknown_sort_call("opaque"),
        rhs_term=_unknown_sort_call("other"),
        provenance=_provenance(),
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
    assert payload["r"]["unknown_sort_equality_seats"] == report.unknown_sort_equality.r
