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
from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report

ROOT = Path(__file__).resolve().parents[4]

EXPECTED_UNTYPED_VECTOR = {
    "python": {
        "AuditMemento": 3,
        "CallEdgeDecl": 2,
        "EqualityFact": 3,
        "FactoryWalkMemento": 1,
        "FunctionContract": 10,
        "RefusalRecord": 3,
        "UniverseMint": 2,
        "VendorConjoin": 3,
    },
    "rust-annex": {
        "RefusalRecord": 3,
    },
}

EXPECTED_ROWS = [
    ("python", "factory/literal_call_report.py", 200, "RefusalRecord"),
    ("python", "factory/literal_call_report.py", 776, "EqualityFact"),
    ("python", "factory/literal_call_report.py", 829, "EqualityFact"),
    ("python", "factory/literal_call_report.py", 1254, "FunctionContract"),
    ("python", "factory/literal_call_report.py", 1256, "FunctionContract"),
    ("python", "factory/literal_call_report.py", 1268, "FunctionContract"),
    ("python", "factory/literal_call_report.py", 1294, "UniverseMint"),
    ("python", "factory/literal_call_report.py", 1321, "FunctionContract"),
    ("python", "factory/literal_call_report.py", 1410, "FunctionContract"),
    ("python", "factory/literal_call_report.py", 1412, "FunctionContract"),
    ("python", "factory/literal_call_report.py", 1428, "FunctionContract"),
    ("python", "factory/literal_call_report.py", 1456, "UniverseMint"),
    ("python", "factory/literal_call_report.py", 1485, "FunctionContract"),
    ("python", "factory/literal_call_report.py", 1582, "CallEdgeDecl"),
    ("python", "factory/literal_call_report.py", 1794, "AuditMemento"),
    ("python", "factory/literal_call_report.py", 1824, "FactoryWalkMemento"),
    ("python", "kit_rpc/body_universe_dto.py", 15, "FunctionContract"),
    ("python", "kit_rpc/body_universe_dto.py", 16, "FunctionContract"),
    ("python", "kit_rpc/body_universe_dto.py", 17, "EqualityFact"),
    ("python", "kit_rpc/lift_report_payload_dto.py", 24, "AuditMemento"),
    ("python", "kit_rpc/lift_report_payload_dto.py", 35, "CallEdgeDecl"),
    ("python", "kit_rpc/lift_report_payload_dto.py", 36, "VendorConjoin"),
    ("python", "kit_rpc/lift_report_payload_dto.py", 37, "VendorConjoin"),
    ("python", "kit_rpc/lift_report_payload_dto.py", 67, "AuditMemento"),
    ("python", "factory/dig_refusal.py", 16, "RefusalRecord"),
    ("python", "factory/floor_contract_agreement.py", 19, "RefusalRecord"),
    ("python", "factory/floor_contract_agreement.py", 29, "VendorConjoin"),
    ("rust-annex", "implementations/rust/sugar-walk/src/contract.rs", 142, "RefusalRecord"),
    ("rust-annex", "implementations/rust/sugar-walk/src/envelope.rs", 318, "RefusalRecord"),
    ("rust-annex", "implementations/rust/sugar-walk/src/lift.rs", 3678, "RefusalRecord"),
]


def test_proofir_vocab_census_pins_current_untyped_emission_sites() -> None:
    report = collect_proofir_vocabulary_frontier(ROOT)

    assert report.untyped_emission_vector == EXPECTED_UNTYPED_VECTOR
    assert report.untyped_emission_total == 30
    assert [
        (site.kit, site.path, site.line, site.node_class)
        for site in report.untyped_emission_sites
    ] == sorted(EXPECTED_ROWS)
    assert report.formula_fragments_without_provenance == 15
    assert report.proofir_classes_without_verdict_witnesses == 4


def test_proofir_vocab_cli_exits_red_with_pinned_vectors(capsys) -> None:
    status = cli.main(["--root", str(ROOT), "--proofir-vocab-frontier"])

    assert status == 1
    stdout = capsys.readouterr().out
    assert "ProofIR semantic vocabulary frontier" in stdout
    assert "R(untyped-emission-sites): 30" in stdout
    assert "python FunctionContract: 10" in stdout
    assert "rust-annex RefusalRecord: 3" in stdout
    assert "R(formula-fragments-without-provenance): 15" in stdout
    assert "R(proofir-classes-without-verdict-witnesses): 4" in stdout
    assert "factory/literal_call_report.py:776" in stdout
    assert "replacement: EqualityFact" in stdout


def test_proofir_vocab_bad_twin_flags_fresh_raw_dict_emission(tmp_path) -> None:
    kit_src = tmp_path / "src" / "sugar_lift_py_tests" / "consumer"
    kit_src.mkdir(parents=True)
    (kit_src / "bad_emitter.py").write_text(
        "def planted():\n"
        "    raw_contract: dict[str, object] = {\n"
        "        \"kind\": \"contract\",\n"
        "        \"inv\": {\"kind\": \"atomic\", \"name\": \"bad\", \"args\": []},\n"
        "    }\n"
        "    return raw_contract\n",
        encoding="utf-8",
    )

    report = collect_proofir_vocabulary_frontier(tmp_path)

    assert report.untyped_emission_total == 1
    offender = report.untyped_emission_sites[0]
    assert offender.path == "consumer/bad_emitter.py"
    assert offender.line == 2
    assert offender.node_class == "EqualityFact"
    assert offender.replacement == "EqualityFact"
    assert "raw dict contract/formula emission" in offender.observed


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


def test_proofir_vocab_provenance_counter_is_payload_diagnostic() -> None:
    report = build_literal_call_report(
        source=(
            "def h(x):\n"
            "    return x + 1\n"
            "def t():\n"
            "    assert h(5) == 6\n"
        ),
        filename="t.py",
        memento_file="t.py",
    )

    diagnostic = next(
        row
        for row in report.payload.diagnostics
        if row.get("kind") == "proofir-formula-provenance"
    )

    assert diagnostic["r"]["formula_fragments_without_provenance"] > 0
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
