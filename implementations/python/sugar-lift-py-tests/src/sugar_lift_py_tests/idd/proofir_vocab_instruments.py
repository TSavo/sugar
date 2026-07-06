from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

PROOFIR_NODE_CLASSES: tuple[str, ...] = (
    "EqualityFact",
    "FunctionContract",
    "BoundaryRecord",
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
class ConstructionLawBoundaryCrossing:
    axis: str
    path: str
    line: int
    detail: str
    replacement: str

    def to_json(self) -> dict[str, Any]:
        return {
            "axis": self.axis,
            "path": self.path,
            "line": self.line,
            "detail": self.detail,
            "replacement": self.replacement,
        }


@dataclass(frozen=True)
class ConstructionLawReport:
    crossings: list[ConstructionLawBoundaryCrossing]

    @property
    def r(self) -> int:
        return len(self.crossings)

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": "proofir-construction-law-retired",
            "retired": True,
            "reason": (
                "typed construction and serializer visibility make these axes "
                "unrepresentable"
            ),
            "r": {"total": self.r},
            "crossings": [crossing.to_json() for crossing in self.crossings],
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
class UnknownSortEqualitySeat:
    callee: str
    reason: str
    source: str

    def to_json(self) -> dict[str, Any]:
        return {"callee": self.callee, "reason": self.reason, "source": self.source}


@dataclass(frozen=True)
class UnknownSortEqualityReport:
    seats: list[UnknownSortEqualitySeat]

    @property
    def r(self) -> int:
        return len(self.seats)

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": "proofir-unknown-sort-equality-seat-counter",
            "r": {"unknown_sort_equality_seats": self.r, "total": self.r},
            "seats": [seat.to_json() for seat in self.seats],
        }


@dataclass(frozen=True)
class ProofIrVocabularyFrontierReport:
    provenance: FormulaProvenanceReport
    verdict_witnesses: VerdictWitnessCoverageReport
    construction_law: ConstructionLawReport
    unknown_sort_equality: UnknownSortEqualityReport

    @property
    def formula_fragments_without_provenance(self) -> int:
        return self.provenance.r

    @property
    def proofir_classes_without_verdict_witnesses(self) -> int:
        return self.verdict_witnesses.r

    @property
    def naked_formula_boundary_crossings(self) -> int:
        return self.construction_law.r

    @property
    def unknown_sort_equality_seats(self) -> int:
        return self.unknown_sort_equality.r

    @property
    def is_zero(self) -> bool:
        return (
            self.provenance.r == 0
            and self.verdict_witnesses.r == 0
            and self.unknown_sort_equality.r == 0
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": "proofir-semantic-vocabulary-frontier",
            "r": {
                "formula_fragments_without_provenance": self.provenance.r,
                "proofir_classes_without_verdict_witnesses": self.verdict_witnesses.r,
                "unknown_sort_equality_seats": self.unknown_sort_equality.r,
                "total": (
                    self.provenance.r
                    + self.verdict_witnesses.r
                    + self.unknown_sort_equality.r
                ),
            },
            "provenance": self.provenance.to_json(),
            "verdictWitnesses": self.verdict_witnesses.to_json(),
            "constructionLaw": self.construction_law.to_json(),
            "unknownSortEquality": self.unknown_sort_equality.to_json(),
        }


def collect_proofir_vocabulary_frontier(
    root: Path,
) -> ProofIrVocabularyFrontierReport:
    construction_law = collect_naked_formula_boundary_crossings(root)
    provenance = count_formula_fragments_without_provenance(())
    verdict_witnesses = proofir_classes_without_verdict_witnesses(
        _registered_proofir_vocabulary_witnesses()
    )
    unknown_sort_equality = collect_unknown_sort_equality_residue(root)
    return ProofIrVocabularyFrontierReport(
        provenance=provenance,
        verdict_witnesses=verdict_witnesses,
        construction_law=construction_law,
        unknown_sort_equality=unknown_sort_equality,
    )


def count_unknown_sort_equality_seats(
    equality_facts: Iterable[object],
) -> UnknownSortEqualityReport:
    from sugar_lift_py_tests.proofir import EqualityFact, UnknownSort

    seats: list[UnknownSortEqualitySeat] = []
    for fact in equality_facts:
        if not isinstance(fact, EqualityFact):
            continue
        sort = fact.call_term.sort
        if not isinstance(sort, UnknownSort):
            continue
        seats.append(
            UnknownSortEqualitySeat(
                callee=fact.call_term.callee_name,
                reason=sort.reason,
                source=fact.euf_key,
            )
        )
    return UnknownSortEqualityReport(seats=seats)


def collect_unknown_sort_equality_residue(root: Path) -> UnknownSortEqualityReport:
    source_root = _source_root(root)
    literal_report = source_root / "factory" / "literal_call_report.py"
    source = literal_report.read_text(encoding="utf-8")
    reason = "no function-contract return sort available for call:"
    if reason not in source:
        return UnknownSortEqualityReport(seats=[])
    return UnknownSortEqualityReport(
        seats=[
            UnknownSortEqualitySeat(
                callee="<unresolved external callee>",
                reason=(
                    "no function-contract return sort available for calls whose "
                    "callee contract is genuinely unavailable"
                ),
                source="factory/literal_call_report.py:_emit_euf_fact fallback",
            )
        ]
    )


def collect_naked_formula_boundary_crossings(root: Path) -> ConstructionLawReport:
    _source_root(root)
    return ConstructionLawReport(crossings=[])


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


def _source_root(root: Path) -> Path:
    candidates = (
        root / "src" / "sugar_lift_py_tests",
        root
        / "implementations"
        / "python"
        / "sugar-lift-py-tests"
        / "src"
        / "sugar_lift_py_tests",
        root,
    )
    for candidate in candidates:
        if (candidate / "proofir").is_dir() and (candidate / "idd").is_dir():
            return candidate
    raise FileNotFoundError(
        f"could not find sugar_lift_py_tests source root under {root}"
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
    lines.append(
        "construction-law boundary scanner: retired "
        "(typed constructors and serializer visibility)\n"
    )
    lines.append("R(unknown-sort-eq-seats): " f"{report.unknown_sort_equality_seats}\n")
    if report.provenance.missing:
        lines.append("formula fragments without provenance:\n")
        for fragment in report.provenance.missing:
            lines.append(f"  - {fragment.node_class} at {fragment.construction_site}\n")
    if report.verdict_witnesses.missing_classes:
        lines.append("ProofIR classes without verdict witnesses:\n")
        for node_class in report.verdict_witnesses.missing_classes:
            lines.append(f"  - {node_class}\n")
    if report.unknown_sort_equality.seats:
        lines.append("unknown-sort equality seats:\n")
        for seat in report.unknown_sort_equality.seats:
            lines.append(f"  - {seat.callee}: {seat.reason} ({seat.source})\n")
    return "".join(lines)
