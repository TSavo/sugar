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
class UntypedEmissionSite:
    kit: str
    path: str
    line: int
    node_class: str
    replacement: str
    observed: str
    formula_fragment: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "kit": self.kit,
            "path": self.path,
            "line": self.line,
            "nodeClass": self.node_class,
            "replacement": self.replacement,
            "observed": self.observed,
            "formulaFragment": self.formula_fragment,
        }


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
    untyped_emission_sites: list[UntypedEmissionSite]
    provenance: FormulaProvenanceReport
    verdict_witnesses: VerdictWitnessCoverageReport

    @property
    def untyped_emission_vector(self) -> dict[str, dict[str, int]]:
        values: dict[str, dict[str, int]] = {}
        for site in self.untyped_emission_sites:
            values.setdefault(site.kit, {})
            values[site.kit][site.node_class] = (
                values[site.kit].get(site.node_class, 0) + 1
            )
        return {
            kit: dict(sorted(node_counts.items()))
            for kit, node_counts in sorted(values.items())
        }

    @property
    def untyped_emission_total(self) -> int:
        return len(self.untyped_emission_sites)

    @property
    def formula_fragments_without_provenance(self) -> int:
        return self.provenance.r

    @property
    def proofir_classes_without_verdict_witnesses(self) -> int:
        return self.verdict_witnesses.r

    @property
    def is_zero(self) -> bool:
        return (
            self.untyped_emission_total == 0
            and self.provenance.r == 0
            and self.verdict_witnesses.r == 0
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": "proofir-semantic-vocabulary-frontier",
            "r": {
                "untyped_emission_sites": self.untyped_emission_total,
                "formula_fragments_without_provenance": self.provenance.r,
                "proofir_classes_without_verdict_witnesses": self.verdict_witnesses.r,
                "total": (
                    self.untyped_emission_total
                    + self.provenance.r
                    + self.verdict_witnesses.r
                ),
            },
            "untypedEmissionVector": self.untyped_emission_vector,
            "untypedEmissionSites": [
                site.to_json() for site in self.untyped_emission_sites
            ],
            "provenance": self.provenance.to_json(),
            "verdictWitnesses": self.verdict_witnesses.to_json(),
        }


@dataclass(frozen=True)
class _PinnedEmissionSpec:
    kit: str
    path: str
    line_hint: int
    needle: str
    node_class: str
    replacement: str
    observed: str
    formula_fragment: bool = False


_PYTHON_SPECS: tuple[_PinnedEmissionSpec, ...] = (
    _PinnedEmissionSpec(
        "python",
        "factory/literal_call_report.py",
        200,
        "refusal.to_json()",
        "RefusalRecord",
        "RefusalRecord",
        "diagnostics list serializes DigRefusal as raw dict",
    ),
    _PinnedEmissionSpec(
        "python",
        "factory/literal_call_report.py",
        776,
        "inv = _formula_to_rpc(fact.fact_formula())",
        "EqualityFact",
        "EqualityFact",
        "_emit_euf_fact flattens typed Formula into raw RPC dict",
        formula_fragment=True,
    ),
    _PinnedEmissionSpec(
        "python",
        "factory/literal_call_report.py",
        829,
        "inv = _formula_to_rpc(formula)",
        "EqualityFact",
        "EqualityFact",
        "_emit_assertion_surface_fact flattens typed Formula into raw RPC dict",
        formula_fragment=True,
    ),
    _PinnedEmissionSpec(
        "python",
        "factory/literal_call_report.py",
        1254,
        "body_formula_values = [_formula_to_rpc(formula) for formula in body_formulas]",
        "FunctionContract",
        "FunctionContract",
        "function universe body formulas are stored as raw RPC dicts",
        formula_fragment=True,
    ),
    _PinnedEmissionSpec(
        "python",
        "factory/literal_call_report.py",
        1256,
        "_formula_to_rpc(formula) if formula is not None else None",
        "FunctionContract",
        "FunctionContract",
        "function universe body-step formulas are stored as raw RPC dicts",
        formula_fragment=True,
    ),
    _PinnedEmissionSpec(
        "python",
        "factory/literal_call_report.py",
        1268,
        "_formula_to_rpc(_universe_formulas[0])",
        "FunctionContract",
        "FunctionContract",
        "function universe post is stored as a raw RPC dict",
        formula_fragment=True,
    ),
    _PinnedEmissionSpec(
        "python",
        "factory/literal_call_report.py",
        1294,
        "function_contract = BodyUniverseDto(",
        "UniverseMint",
        "UniverseMint",
        "function universe mints a raw BodyUniverse DTO row",
        formula_fragment=True,
    ),
    _PinnedEmissionSpec(
        "python",
        "factory/literal_call_report.py",
        1321,
        "emitted_formula=(",
        "FunctionContract",
        "FunctionContract",
        "factory walk row carries a raw body-step formula dict",
        formula_fragment=True,
    ),
    _PinnedEmissionSpec(
        "python",
        "factory/literal_call_report.py",
        1410,
        "body_formula_values = [_formula_to_rpc(formula) for formula in body_formulas]",
        "FunctionContract",
        "FunctionContract",
        "dig universe body formulas are stored as raw RPC dicts",
        formula_fragment=True,
    ),
    _PinnedEmissionSpec(
        "python",
        "factory/literal_call_report.py",
        1412,
        "_formula_to_rpc(formula) if formula is not None else None",
        "FunctionContract",
        "FunctionContract",
        "dig universe body-step formulas are stored as raw RPC dicts",
        formula_fragment=True,
    ),
    _PinnedEmissionSpec(
        "python",
        "factory/literal_call_report.py",
        1428,
        "_formula_to_rpc(_universe_formulas[0])",
        "FunctionContract",
        "FunctionContract",
        "dig universe post is stored as a raw RPC dict",
        formula_fragment=True,
    ),
    _PinnedEmissionSpec(
        "python",
        "factory/literal_call_report.py",
        1456,
        "function_contract = BodyUniverseDto(",
        "UniverseMint",
        "UniverseMint",
        "dig universe mints a raw BodyUniverse DTO row",
        formula_fragment=True,
    ),
    _PinnedEmissionSpec(
        "python",
        "factory/literal_call_report.py",
        1485,
        "emitted_formula=(",
        "FunctionContract",
        "FunctionContract",
        "dig factory walk row carries a raw body-step formula dict",
        formula_fragment=True,
    ),
    _PinnedEmissionSpec(
        "python",
        "factory/literal_call_report.py",
        1582,
        "edge: dict[str, Any] = {",
        "CallEdgeDecl",
        "CallEdgeDecl-reuse",
        "call-edge is hand-built as a raw dict instead of typed CallEdgeDecl",
    ),
    _PinnedEmissionSpec(
        "python",
        "factory/literal_call_report.py",
        1794,
        "return {",
        "AuditMemento",
        "AuditMemento",
        "_source_audit returns a raw audit memento dict",
    ),
    _PinnedEmissionSpec(
        "python",
        "factory/literal_call_report.py",
        1824,
        "emitted_formula: dict[str, Any] | None = None",
        "FactoryWalkMemento",
        "AuditMemento",
        "_walk_row stores emittedFormula as a raw dict slot",
    ),
    _PinnedEmissionSpec(
        "python",
        "kit_rpc/body_universe_dto.py",
        15,
        "pre: dict[str, Any] | None = None",
        "FunctionContract",
        "FunctionContract",
        "BodyUniverseDto.pre is a raw formula dict slot",
        formula_fragment=True,
    ),
    _PinnedEmissionSpec(
        "python",
        "kit_rpc/body_universe_dto.py",
        16,
        "post: dict[str, Any] | None = None",
        "FunctionContract",
        "FunctionContract",
        "BodyUniverseDto.post is a raw formula dict slot",
        formula_fragment=True,
    ),
    _PinnedEmissionSpec(
        "python",
        "kit_rpc/body_universe_dto.py",
        17,
        "inv: dict[str, Any] | None = None",
        "EqualityFact",
        "EqualityFact",
        "BodyUniverseDto.inv is a raw formula dict slot",
        formula_fragment=True,
    ),
    _PinnedEmissionSpec(
        "python",
        "kit_rpc/lift_report_payload_dto.py",
        24,
        "source_audits: list[dict[str, Any]]",
        "AuditMemento",
        "AuditMemento",
        "LiftReportPayloadDto.source_audits stores raw audit dicts",
    ),
    _PinnedEmissionSpec(
        "python",
        "kit_rpc/lift_report_payload_dto.py",
        35,
        "call_edges: list[dict[str, Any]]",
        "CallEdgeDecl",
        "CallEdgeDecl-reuse",
        "LiftReportPayloadDto.call_edges stores raw edge dicts",
    ),
    _PinnedEmissionSpec(
        "python",
        "kit_rpc/lift_report_payload_dto.py",
        36,
        "vendor_conjoins: list[dict[str, Any]]",
        "VendorConjoin",
        "VendorConjoin",
        "LiftReportPayloadDto.vendor_conjoins stores raw vendor-conjoin dicts",
    ),
    _PinnedEmissionSpec(
        "python",
        "kit_rpc/lift_report_payload_dto.py",
        37,
        "diagnostics: list[dict[str, Any]]",
        "VendorConjoin",
        "VendorConjoin",
        "LiftReportPayloadDto.diagnostics stores raw diagnostic dicts",
    ),
    _PinnedEmissionSpec(
        "python",
        "kit_rpc/lift_report_payload_dto.py",
        67,
        "def _default_source_ledger",
        "AuditMemento",
        "AuditMemento",
        "source ledger is synthesized as a raw audit counter dict",
    ),
    _PinnedEmissionSpec(
        "python",
        "factory/dig_refusal.py",
        16,
        "def to_json(self) -> dict[str, Any]:",
        "RefusalRecord",
        "RefusalRecord",
        "DigRefusal serializes to a raw refusal dict",
    ),
    _PinnedEmissionSpec(
        "python",
        "factory/floor_contract_agreement.py",
        19,
        "def to_json(self) -> dict[str, Any]:",
        "RefusalRecord",
        "RefusalRecord",
        "FloorContractAgreementViolation serializes to a raw refusal dict",
    ),
    _PinnedEmissionSpec(
        "python",
        "factory/floor_contract_agreement.py",
        29,
        "def floor_contract_agreement_diagnostic(",
        "VendorConjoin",
        "VendorConjoin",
        "floor-contract agreement diagnostic is a raw diagnostic dict",
    ),
)

_RUST_ANNEX_SPECS: tuple[_PinnedEmissionSpec, ...] = (
    _PinnedEmissionSpec(
        "rust-annex",
        "implementations/rust/sugar-walk/src/contract.rs",
        142,
        ".push(crate::canonical::serde_to_canonical(serde_json::json!({",
        "RefusalRecord",
        "RefusalRecord",
        "panic locus is emitted through raw serde_json::json! scaffolding",
    ),
    _PinnedEmissionSpec(
        "rust-annex",
        "implementations/rust/sugar-walk/src/envelope.rs",
        318,
        "Value::object([",
        "RefusalRecord",
        "RefusalRecord",
        "test panic locus helper uses raw Value object scaffolding",
    ),
    _PinnedEmissionSpec(
        "rust-annex",
        "implementations/rust/sugar-walk/src/lift.rs",
        3685,
        "let mut locus = serde_json::json!({",
        "RefusalRecord",
        "RefusalRecord",
        "panic locus is emitted through raw serde_json::json! scaffolding",
    ),
)


def collect_proofir_vocabulary_frontier(
    root: Path,
) -> ProofIrVocabularyFrontierReport:
    sites = sorted(
        [
            *_collect_pinned_sites(root),
            *_collect_planted_raw_dict_sites(root),
        ],
        key=lambda site: (site.kit, site.path, site.line, site.node_class),
    )
    provenance = count_formula_fragments_without_provenance(
        [
            FormulaFragmentProbe(
                node_class=site.node_class,
                construction_site=f"{site.path}:{site.line}",
                provenance=None,
            )
            for site in sites
            if site.formula_fragment
        ]
    )
    verdict_witnesses = proofir_classes_without_verdict_witnesses(
        _registered_proofir_vocabulary_witnesses()
    )
    return ProofIrVocabularyFrontierReport(
        untyped_emission_sites=sites,
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
    lines.append(f"R(untyped-emission-sites): {report.untyped_emission_total}\n")
    for kit, values in report.untyped_emission_vector.items():
        for node_class, count in values.items():
            lines.append(f"  {kit} {node_class}: {count}\n")
    lines.append(
        "R(formula-fragments-without-provenance): "
        f"{report.formula_fragments_without_provenance}\n"
    )
    lines.append(
        "R(proofir-classes-without-verdict-witnesses): "
        f"{report.proofir_classes_without_verdict_witnesses}\n"
    )
    if report.untyped_emission_sites:
        lines.append("untyped emission sites:\n")
        for site in report.untyped_emission_sites:
            lines.append(
                f"  - {site.kit} {site.path}:{site.line} "
                f"{site.node_class}; replacement: {site.replacement}; "
                f"{site.observed}\n"
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


def _collect_pinned_sites(root: Path) -> list[UntypedEmissionSite]:
    kit_src = _kit_src(root)
    sites: list[UntypedEmissionSite] = []
    for spec in _PYTHON_SPECS:
        path = kit_src / spec.path
        site = _site_from_spec(path, spec)
        if site is not None:
            sites.append(site)
    for spec in _RUST_ANNEX_SPECS:
        path = root / spec.path
        site = _site_from_spec(path, spec)
        if site is not None:
            sites.append(site)
    return sites


def _site_from_spec(path: Path, spec: _PinnedEmissionSpec) -> UntypedEmissionSite | None:
    if not path.exists():
        return None
    lines = path.read_text(encoding="utf-8").splitlines()
    line = _find_line_near(lines, spec.needle, spec.line_hint)
    if line is None:
        return None
    return UntypedEmissionSite(
        kit=spec.kit,
        path=spec.path,
        line=line,
        node_class=spec.node_class,
        replacement=spec.replacement,
        observed=spec.observed,
        formula_fragment=spec.formula_fragment,
    )


def _find_line_near(lines: list[str], needle: str, line_hint: int) -> int | None:
    matches = [
        index
        for index, line in enumerate(lines, start=1)
        if needle in line
    ]
    if not matches:
        return None
    return min(matches, key=lambda line: abs(line - line_hint))


def _collect_planted_raw_dict_sites(root: Path) -> list[UntypedEmissionSite]:
    kit_src = _kit_src(root)
    if not kit_src.exists():
        return []
    sites: list[UntypedEmissionSite] = []
    pinned_paths = {spec.path for spec in _PYTHON_SPECS}
    for path in sorted(kit_src.rglob("*.py")):
        rel = path.relative_to(kit_src).as_posix()
        if rel in pinned_paths:
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines, start=1):
            window = "\n".join(lines[index - 1 : index + 5])
            if (
                ": dict[" in line
                and "= {" in line
                and '"kind": "contract"' in window
                and ('"inv"' in window or '"post"' in window or '"pre"' in window)
            ):
                sites.append(
                    UntypedEmissionSite(
                        kit="python",
                        path=rel,
                        line=index,
                        node_class="EqualityFact",
                        replacement="EqualityFact",
                        observed="raw dict contract/formula emission outside typed vocabulary",
                        formula_fragment=True,
                    )
                )
    return sites


def _kit_src(root: Path) -> Path:
    candidates = (
        root / "implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests",
        root / "python/sugar-lift-py-tests/src/sugar_lift_py_tests",
        root / "src/sugar_lift_py_tests",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]
