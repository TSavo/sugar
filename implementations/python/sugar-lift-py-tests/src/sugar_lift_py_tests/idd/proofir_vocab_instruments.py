from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

PROOFIR_NODE_CLASSES: tuple[str, ...] = (
    "EqualityFact",
    "FunctionContract",
    "RefusalRecord",
    "CallEdgeDecl",
    "AuditMemento",
    "UniverseMint",
    "VendorConjoin",
)


@dataclass(frozen=True)
class FormulaFragmentProbe:
    node_class: str
    construction_site: str | None
    provenance: dict[str, Any] | None

    def to_json(self) -> dict[str, Any]:
        return {
            "nodeClass": self.node_class,
            "constructionSite": self.construction_site,
            "provenance": self.provenance,
        }


@dataclass(frozen=True)
class FormulaProvenanceReport:
    missing: list[FormulaFragmentProbe]

    @property
    def r(self) -> int:
        return len(self.missing)

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": "proofir-formula-provenance-counter",
            "r": {"formula_fragments_without_provenance": self.r, "total": self.r},
            "missing": [fragment.to_json() for fragment in self.missing],
        }


@dataclass(frozen=True)
class ProofIrVocabularyWitness:
    node_class: str
    truthful_sat: bool
    lying_unsat: bool


@dataclass(frozen=True)
class VerdictWitnessCoverageReport:
    missing_classes: list[str]

    @property
    def r(self) -> int:
        return len(self.missing_classes)

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": "proofir-verdict-witness-coverage-counter",
            "r": {"proofir_classes_without_verdict_witnesses": self.r, "total": self.r},
            "missingClasses": list(self.missing_classes),
        }


@dataclass(frozen=True)
class ProofIrVocabularyFrontierReport:
    provenance: FormulaProvenanceReport
    verdict_witnesses: VerdictWitnessCoverageReport

    @property
    def formula_fragments_without_provenance(self) -> int:
        return self.provenance.r

    @property
    def proofir_classes_without_verdict_witnesses(self) -> int:
        return self.verdict_witnesses.r

    @property
    def is_zero(self) -> bool:
        return self.provenance.r == 0 and self.verdict_witnesses.r == 0

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": "proofir-semantic-vocabulary-frontier",
            "r": {
                "formula_fragments_without_provenance": self.provenance.r,
                "proofir_classes_without_verdict_witnesses": self.verdict_witnesses.r,
                "total": self.provenance.r + self.verdict_witnesses.r,
            },
            "provenance": self.provenance.to_json(),
            "verdictWitnesses": self.verdict_witnesses.to_json(),
        }


_FORMULA_PROVENANCE_BASELINE: tuple[FormulaFragmentProbe, ...] = (
    FormulaFragmentProbe("EqualityFact", "factory/literal_call_report.py:776", None),
    FormulaFragmentProbe("EqualityFact", "factory/literal_call_report.py:829", None),
    FormulaFragmentProbe("FunctionContract", "factory/literal_call_report.py:1254", None),
    FormulaFragmentProbe("FunctionContract", "factory/literal_call_report.py:1256", None),
    FormulaFragmentProbe("FunctionContract", "factory/literal_call_report.py:1268", None),
    FormulaFragmentProbe("UniverseMint", "factory/literal_call_report.py:1294", None),
    FormulaFragmentProbe("FunctionContract", "factory/literal_call_report.py:1321", None),
    FormulaFragmentProbe("FunctionContract", "factory/literal_call_report.py:1410", None),
    FormulaFragmentProbe("FunctionContract", "factory/literal_call_report.py:1412", None),
    FormulaFragmentProbe("FunctionContract", "factory/literal_call_report.py:1428", None),
    FormulaFragmentProbe("UniverseMint", "factory/literal_call_report.py:1456", None),
    FormulaFragmentProbe("FunctionContract", "factory/literal_call_report.py:1485", None),
    FormulaFragmentProbe("FunctionContract", "kit_rpc/body_universe_dto.py:15", None),
    FormulaFragmentProbe("FunctionContract", "kit_rpc/body_universe_dto.py:16", None),
    FormulaFragmentProbe("EqualityFact", "kit_rpc/body_universe_dto.py:17", None),
)


def collect_proofir_vocabulary_frontier(
    root: Path,
) -> ProofIrVocabularyFrontierReport:
    _ = root
    provenance = count_formula_fragments_without_provenance(_FORMULA_PROVENANCE_BASELINE)
    verdict_witnesses = proofir_classes_without_verdict_witnesses(
        _registered_proofir_vocabulary_witnesses()
    )
    return ProofIrVocabularyFrontierReport(
        provenance=provenance,
        verdict_witnesses=verdict_witnesses,
    )


def count_formula_fragments_without_provenance(
    fragments: Iterable[FormulaFragmentProbe],
) -> FormulaProvenanceReport:
    missing = [
        fragment
        for fragment in fragments
        if fragment.construction_site is None or fragment.provenance is None
    ]
    return FormulaProvenanceReport(missing=missing)


def proofir_classes_without_verdict_witnesses(
    witnesses: Iterable[ProofIrVocabularyWitness],
    *,
    node_classes: Sequence[str] = PROOFIR_NODE_CLASSES,
) -> VerdictWitnessCoverageReport:
    witnessed = {
        witness.node_class
        for witness in witnesses
        if witness.truthful_sat and witness.lying_unsat
    }
    missing = [node_class for node_class in node_classes if node_class not in witnessed]
    return VerdictWitnessCoverageReport(missing_classes=missing)


def _registered_proofir_vocabulary_witnesses() -> tuple[ProofIrVocabularyWitness, ...]:
    from sugar_lift_py_tests.proofir import registered_verdict_witnesses

    return tuple(
        ProofIrVocabularyWitness(
            node_class=node_class,
            truthful_sat=truthful_sat,
            lying_unsat=lying_unsat,
        )
        for node_class, truthful_sat, lying_unsat in registered_verdict_witnesses()
    )


def render_text(report: ProofIrVocabularyFrontierReport) -> str:
    lines = ["ProofIR semantic vocabulary frontier\n"]
    lines.append(
        "R(formula-fragments-without-provenance): "
        f"{report.formula_fragments_without_provenance}\n"
    )
    lines.append(
        "R(proofir-classes-without-verdict-witnesses): "
        f"{report.proofir_classes_without_verdict_witnesses}\n"
    )
    if report.provenance.missing:
        lines.append("formula fragments without provenance:\n")
        for fragment in report.provenance.missing:
            lines.append(
                f"  - {fragment.node_class} at {fragment.construction_site}\n"
            )
    if report.verdict_witnesses.missing_classes:
        lines.append("ProofIR classes without verdict witnesses:\n")
        for node_class in report.verdict_witnesses.missing_classes:
            lines.append(f"  - {node_class}\n")
    return "".join(lines)
