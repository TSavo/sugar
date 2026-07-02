from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from sugar_lift_py_tests.factory.source_fragment import SourceFragment

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
            "kind": "proofir-construction-law-live-scanner",
            "r": {"naked_formula_boundary_crossings": self.r, "total": self.r},
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
class ProofIrVocabularyFrontierReport:
    provenance: FormulaProvenanceReport
    verdict_witnesses: VerdictWitnessCoverageReport
    construction_law: ConstructionLawReport

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
    def is_zero(self) -> bool:
        return (
            self.provenance.r == 0
            and self.verdict_witnesses.r == 0
            and self.construction_law.r == 0
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": "proofir-semantic-vocabulary-frontier",
            "r": {
                "formula_fragments_without_provenance": self.provenance.r,
                "proofir_classes_without_verdict_witnesses": self.verdict_witnesses.r,
                "naked_formula_boundary_crossings": self.construction_law.r,
                "total": (
                    self.provenance.r
                    + self.verdict_witnesses.r
                    + self.construction_law.r
                ),
            },
            "provenance": self.provenance.to_json(),
            "verdictWitnesses": self.verdict_witnesses.to_json(),
            "constructionLaw": self.construction_law.to_json(),
        }


def collect_proofir_vocabulary_frontier(
    root: Path,
) -> ProofIrVocabularyFrontierReport:
    construction_law = collect_naked_formula_boundary_crossings(root)
    provenance = count_formula_fragments_without_provenance(
        _formula_fragments_from_construction_law(construction_law)
    )
    verdict_witnesses = proofir_classes_without_verdict_witnesses(
        _registered_proofir_vocabulary_witnesses()
    )
    return ProofIrVocabularyFrontierReport(
        provenance=provenance,
        verdict_witnesses=verdict_witnesses,
        construction_law=construction_law,
    )


def collect_naked_formula_boundary_crossings(root: Path) -> ConstructionLawReport:
    source_root = _source_root(root)
    crossings: list[ConstructionLawBoundaryCrossing] = []
    split_has_begun = any(
        (source_root / "proofir" / name).is_dir()
        for name in ("sorts", "terms", "formulas", "scope")
    )
    for path in sorted(source_root.rglob("*.py")):
        relpath = path.relative_to(source_root).as_posix()
        if relpath == "idd/proofir_vocab_instruments.py":
            continue
        scanner = _ConstructionLawScanner(
            relpath=relpath,
            split_has_begun=split_has_begun,
        )
        crossings.extend(scanner.scan(path.read_text(encoding="utf-8")))
    crossings.sort(key=lambda crossing: (crossing.path, crossing.line, crossing.axis))
    return ConstructionLawReport(crossings=crossings)


def count_formula_fragments_without_provenance(
    fragments: Iterable[FormulaFragmentProbe],
) -> FormulaProvenanceReport:
    missing = [
        fragment
        for fragment in fragments
        if fragment.construction_site is None or fragment.provenance is None
    ]
    return FormulaProvenanceReport(missing=missing)


def _formula_fragments_from_construction_law(
    report: ConstructionLawReport,
) -> tuple[FormulaFragmentProbe, ...]:
    probes: list[FormulaFragmentProbe] = []
    for crossing in report.crossings:
        if crossing.axis not in {
            "_formula_to_rpc-outside-serializer",
            "raw-BodyUniverseDto-formula-slot",
            "formula-slot-type",
        }:
            continue
        probes.append(
            FormulaFragmentProbe(
                node_class=_provenance_node_class(crossing),
                construction_site=f"{crossing.path}:{crossing.line}",
                provenance=None,
            )
        )
    return tuple(probes)


def _provenance_node_class(crossing: ConstructionLawBoundaryCrossing) -> str:
    if "EqualityFact" in crossing.detail or "literal-call" in crossing.detail:
        return "EqualityFact"
    if crossing.path.endswith("body_universe_dto.py"):
        return "BodyUniverseDto"
    if "RefusalRecord" in crossing.detail:
        return "RefusalRecord"
    if "FunctionContract" in crossing.detail or crossing.detail.endswith(".post: Formula"):
        return "FunctionContract"
    return "ProofIRMember"


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


class _ConstructionLawScanner:
    def __init__(self, *, relpath: str, split_has_begun: bool) -> None:
        self.relpath = relpath
        self.split_has_begun = split_has_begun
        self.crossings: list[ConstructionLawBoundaryCrossing] = []

    def scan(self, source: str) -> list[ConstructionLawBoundaryCrossing]:
        root = SourceFragment.from_source(source, self.relpath)
        for fragment in root.walk():
            if fragment.observed == "Call":
                self._scan_call(fragment)
            elif fragment.observed == "ClassDef":
                self._scan_class(fragment)
        return self.crossings

    def _scan_call(self, fragment: SourceFragment) -> None:
        call_name = _call_name(fragment)
        if call_name == "_formula_to_rpc" and not self._is_proofir_serializer():
            self._add(
                axis="_formula_to_rpc-outside-serializer",
                line=fragment.line,
                detail="_formula_to_rpc lowers a naked Formula outside ProofIR serialization internals",
                replacement="serialize through a typed proofir node member",
            )
        if call_name == "BodyUniverseDto" and not self._is_proofir_serializer():
            for keyword in fragment.call_keywords():
                arg_name = keyword.keyword_arg_name()
                if arg_name in {"pre", "post", "inv"} and not _is_none_literal(
                    keyword.keyword_value()
                ):
                    self._add(
                        axis="raw-BodyUniverseDto-formula-slot",
                        line=fragment.line,
                        detail=f"BodyUniverseDto({arg_name}=...) receives a raw formula slot",
                        replacement="construct a typed proofir node and let its serializer lower the formula",
                    )

    def _scan_class(self, fragment: SourceFragment) -> None:
        class_name = fragment.class_name()
        if (
            self.split_has_begun
            and self.relpath == "proofir/nodes.py"
            and _is_proofir_semantic_class(class_name)
        ):
            self._add(
                axis="monolithic-proofir-semantic-class",
                line=fragment.line,
                detail=f"{class_name} remains in proofir/nodes.py after the tiny-file split began",
                replacement=f"move {class_name} to its proofir/nodes/* role module",
            )
        for statement in fragment.class_body():
            if statement.observed == "AnnAssign":
                self._scan_annotated_slot(statement, owner=class_name)
            elif statement.observed in {"FunctionDef", "AsyncFunctionDef"}:
                self._scan_function_args(statement, owner=class_name)

    def _scan_function_args(self, fragment: SourceFragment, *, owner: str) -> None:
        if self.relpath != "proofir/nodes.py" or not _is_boundary_owner(owner):
            return
        for arg_name, annotation, line in fragment.function_arg_annotations():
            if annotation is not None:
                self._scan_annotation(
                    field_name=arg_name,
                    annotation=annotation,
                    line=line,
                    owner=f"{owner}.{fragment.function_name()}",
                )

    def _scan_annotated_slot(self, fragment: SourceFragment, *, owner: str) -> None:
        if self.relpath not in {
            "proofir/nodes.py",
            "kit_rpc/body_universe_dto.py",
        }:
            return
        if self.relpath == "proofir/nodes.py" and not _is_boundary_owner(owner):
            return
        if _field_init_false(fragment.annassign_value()):
            return
        try:
            target_name = fragment.annassign_target_id()
        except TypeError:
            return
        self._scan_annotation(
            field_name=target_name,
            annotation=fragment.annassign_annotation(),
            line=fragment.line,
            owner=owner,
        )

    def _scan_annotation(
        self,
        *,
        field_name: str,
        annotation: SourceFragment,
        line: int,
        owner: str,
    ) -> None:
        if not _is_formula_boundary_slot(field_name):
            return
        annotation_text = _annotation_text(annotation)
        if not _annotation_crosses_formula_boundary(annotation_text):
            return
        self._add(
            axis="formula-slot-type",
            line=line,
            detail=f"{owner}.{field_name}: {annotation_text}",
            replacement="use the tiny typed proofir role wrapper for this formula boundary",
        )

    def _is_proofir_serializer(self) -> bool:
        return self.relpath.startswith("proofir/")

    def _add(
        self,
        *,
        axis: str,
        line: int,
        detail: str,
        replacement: str,
    ) -> None:
        self.crossings.append(
            ConstructionLawBoundaryCrossing(
                axis=axis,
                path=self.relpath,
                line=line,
                detail=detail,
                replacement=replacement,
            )
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
    raise FileNotFoundError(f"could not find sugar_lift_py_tests source root under {root}")


def _call_name(call_fragment: SourceFragment) -> str:
    if call_fragment.observed != "Call":
        return ""
    return call_fragment.call_target_name() or ""


def _is_none_literal(fragment: SourceFragment) -> bool:
    return fragment.observed == "PrimitiveLiteral" and fragment.literal_value() is None


def _field_init_false(value: SourceFragment | None) -> bool:
    if value is None or value.observed != "Call" or _call_name(value) != "field":
        return False
    return any(
        keyword.keyword_arg_name() == "init"
        and keyword.keyword_value().observed == "PrimitiveLiteral"
        and keyword.keyword_value().literal_value() is False
        for keyword in value.call_keywords()
    )


def _annotation_text(annotation: SourceFragment) -> str:
    return annotation.unparse()


def _is_boundary_owner(owner: str) -> bool:
    return owner in {
        "EqualityFact",
        "FunctionContract",
        "FunctionContractBuilder",
        "RefusalRecord",
    }


def _is_proofir_semantic_class(class_name: str) -> bool:
    return class_name in {"EqualityFact", "FunctionContract", "RefusalRecord"}


def _is_formula_boundary_slot(field_name: str) -> bool:
    return field_name in {
        "euf_key",
        "formula",
        "formulas",
        "inv",
        "post",
        "pre",
        "_post",
        "_pre",
    }


def _annotation_crosses_formula_boundary(annotation_text: str) -> bool:
    compact = annotation_text.replace(" ", "")
    return (
        "Formula" in annotation_text
        or "dict[str,Any]" in compact
        or "Dict[str,Any]" in compact
        or annotation_text in {"Any", "str", "object"}
        or "Any" in annotation_text
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
        "R(naked-formula-boundary-crossings): "
        f"{report.naked_formula_boundary_crossings}\n"
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
    if report.construction_law.crossings:
        lines.append("naked formula boundary crossings:\n")
        for crossing in report.construction_law.crossings:
            lines.append(
                f"  - {crossing.axis} {crossing.path}:{crossing.line}: "
                f"{crossing.detail} -> {crossing.replacement}\n"
            )
    return "".join(lines)
