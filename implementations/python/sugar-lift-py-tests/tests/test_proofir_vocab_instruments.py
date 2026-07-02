from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.idd import cli
from sugar_lift_py_tests.idd.proofir_vocab_instruments import (
    FormulaFragmentProbe,
    ProofIrVocabularyWitness,
    collect_proofir_vocabulary_frontier,
    count_formula_fragments_without_provenance,
    proofir_classes_without_verdict_witnesses,
)
from sugar_lift_py_tests.factory.proofir_provenance_diagnostic import (
    proofir_formula_provenance_diagnostic,
)
from sugar_lift_py_tests.kit_rpc import BodyUniverseDto, FactoryWalkRowDto

ROOT = Path(__file__).resolve().parents[4]

def test_proofir_vocab_instruments_pin_surviving_counters() -> None:
    report = collect_proofir_vocabulary_frontier(ROOT)

    assert report.formula_fragments_without_provenance > 0
    assert (
        report.formula_fragments_without_provenance
        == len(report.provenance.missing)
    )
    assert report.proofir_classes_without_verdict_witnesses == 4
    assert report.naked_formula_boundary_crossings > 0


def test_proofir_vocab_cli_exits_red_with_pinned_vectors(capsys) -> None:
    status = cli.main(["--root", str(ROOT), "--proofir-vocab-frontier"])

    assert status == 1
    stdout = capsys.readouterr().out
    assert "ProofIR semantic vocabulary frontier" in stdout
    assert "R(untyped-emission-sites)" not in stdout
    assert "R(formula-fragments-without-provenance):" in stdout
    assert "R(proofir-classes-without-verdict-witnesses): 4" in stdout
    assert "R(naked-formula-boundary-crossings):" in stdout


def test_proofir_vocab_provenance_counter_tooth() -> None:
    clean = FormulaFragmentProbe(
        node_class="EqualityFact",
        construction_site="test:1",
        provenance={"warrant": "Stated(test:1)"},
    )
    missing = FormulaFragmentProbe(
        node_class="FunctionContract",
        construction_site="test:2",
        provenance=None,
    )

    report = count_formula_fragments_without_provenance([clean, missing])

    assert report.r == 1
    assert [fragment.node_class for fragment in report.missing] == ["FunctionContract"]


def test_proofir_vocab_provenance_counter_is_payload_diagnostic_shape() -> None:
    diagnostic = proofir_formula_provenance_diagnostic(
        [
            BodyUniverseDto(
                name="h#euf#c:call:h(i:5)::assertion",
                inv={"kind": "atomic", "name": "=", "args": []},
                proofir_provenance={
                    "kind": "proofir-provenance",
                    "nodeClass": "EqualityFact",
                },
            ),
            BodyUniverseDto(
                name="t::f::callable",
                post={"kind": "atomic", "name": "=", "args": []},
            ),
        ],
        [
            FactoryWalkRowDto(
                file="t.py",
                line=4,
                requested_role="AssertionSurface",
                ast_kind="Assert",
                selected="CallSugar",
                status="warranted",
                output="predicate",
                source_memento={"kind": "source-memento", "file": "t.py"},
                emitted_formula={"kind": "atomic", "name": "=", "args": []},
            )
        ],
    )

    assert diagnostic["r"]["formula_fragments_without_provenance"] > 0
    assert not any(
        row["constructionSite"] == "h#euf#c:call:h(i:5)::assertion.inv"
        for row in diagnostic["missing"]
    )
    assert diagnostic["r"]["total"] == len(diagnostic["missing"])
    assert all("nodeClass" in row for row in diagnostic["missing"])
    assert all("constructionSite" in row for row in diagnostic["missing"])


def test_proofir_vocab_verdict_witness_counter_flags_missing_class_witness() -> None:
    witnesses = [
        ProofIrVocabularyWitness(node_class="EqualityFact", truthful_sat=True, lying_unsat=True)
    ]

    report = proofir_classes_without_verdict_witnesses(witnesses)

    assert report.r == 6
    assert "EqualityFact" not in report.missing_classes
    assert "FunctionContract" in report.missing_classes


def test_proofir_vocab_verdict_witness_bad_twin_flags_dummy_class() -> None:
    witnesses = [
        ProofIrVocabularyWitness(node_class="EqualityFact", truthful_sat=True, lying_unsat=True)
    ]

    report = proofir_classes_without_verdict_witnesses(
        witnesses,
        node_classes=("EqualityFact", "DummyNode"),
    )

    assert report.r == 1
    assert report.missing_classes == ["DummyNode"]
