from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from sugar_lift_py_tests import floor as floor_pkg
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.sugar.witnesses import (
    NotVerdictBearing,
    SugarWitnessPair,
    WitnessSource,
)
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


@dataclass(frozen=True)
class UnenrolledSugar:
    name: str
    module: str
    role: str

    def to_json(self) -> dict[str, Any]:
        return {"name": self.name, "module": self.module, "role": self.role}


SugarWitnessSeed = SugarWitnessPair


@dataclass(frozen=True)
class NonFolOptOut:
    sugar_name: str
    floor_name: str
    reason: str
    retirement_condition: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "sugarName": self.sugar_name,
            "floorName": self.floor_name,
            "reason": self.reason,
            "retirementCondition": self.retirement_condition,
        }


@dataclass(frozen=True)
class NonFolOptOutAudit:
    pinned_but_unmarked: tuple[NonFolOptOut, ...]
    marked_but_unpinned: tuple[str, ...]

    @property
    def is_zero(self) -> bool:
        return not self.pinned_but_unmarked and not self.marked_but_unpinned

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": "sugar-witness-non-fol-opt-out-audit",
            "r": {
                "pinned_but_unmarked": len(self.pinned_but_unmarked),
                "marked_but_unpinned": len(self.marked_but_unpinned),
                "total": len(self.pinned_but_unmarked)
                + len(self.marked_but_unpinned),
            },
            "pinnedButUnmarked": [
                row.to_json() for row in self.pinned_but_unmarked
            ],
            "markedButUnpinned": list(self.marked_but_unpinned),
        }


@dataclass(frozen=True)
class WitnessTripleFailure:
    seed: str
    owner_sugar: str
    variant: str
    axis: str
    expected: str
    observed: str

    def to_json(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "ownerSugar": self.owner_sugar,
            "variant": self.variant,
            "axis": self.axis,
            "expected": self.expected,
            "observed": self.observed,
        }


@dataclass(frozen=True)
class NonCircularityFailure:
    seed: str
    expected_sugar: str
    selected_sugars: tuple[str, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "expectedSugar": self.expected_sugar,
            "selectedSugars": list(self.selected_sugars),
        }


@dataclass(frozen=True)
class SugarWitnessSeedReport:
    seed_count: int
    unique_owner_count: int
    catalog_count: int
    triple_failures: tuple[WitnessTripleFailure, ...]
    non_circularity_failures: tuple[NonCircularityFailure, ...]

    @property
    def witness_triples_failing(self) -> int:
        return len({failure.seed for failure in self.triple_failures})

    @property
    def witnesses_not_dispatching_to_owner(self) -> int:
        return len(self.non_circularity_failures)

    @property
    def is_zero(self) -> bool:
        return (
            self.witness_triples_failing == 0
            and self.witnesses_not_dispatching_to_owner == 0
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": "sugar-witness-seed-harness",
            "seedCount": self.seed_count,
            "uniqueOwnerCount": self.unique_owner_count,
            "catalogCount": self.catalog_count,
            "r": {
                "witness_triples_failing": self.witness_triples_failing,
                "witnesses_not_dispatching_to_owner": (
                    self.witnesses_not_dispatching_to_owner
                ),
                "total": self.witness_triples_failing
                + self.witnesses_not_dispatching_to_owner,
            },
            "tripleFailures": [
                failure.to_json() for failure in self.triple_failures
            ],
            "nonCircularityFailures": [
                failure.to_json() for failure in self.non_circularity_failures
            ],
        }


@dataclass(frozen=True)
class SugarWitnessFrontierReport:
    unenrolled_sugars: tuple[UnenrolledSugar, ...]
    seed_report: SugarWitnessSeedReport
    opt_out_audit: NonFolOptOutAudit
    temporal_opt_outs: tuple[NonFolOptOut, ...]

    @property
    def is_zero(self) -> bool:
        return (
            not self.unenrolled_sugars
            and self.seed_report.is_zero
            and self.opt_out_audit.is_zero
            and not self.temporal_opt_outs
        )

    def to_json(self) -> dict[str, Any]:
        opt_out_r = self.opt_out_audit.to_json()["r"]
        return {
            "kind": "sugar-witness-frontier",
            "r": {
                "unenrolled_sugars": len(self.unenrolled_sugars),
                "witness_triples_failing": (
                    self.seed_report.witness_triples_failing
                ),
                "witnesses_not_dispatching_to_owner": (
                    self.seed_report.witnesses_not_dispatching_to_owner
                ),
                "non_fol_opt_out_drift": opt_out_r["total"],
                "temporal_opt_outs": len(self.temporal_opt_outs),
                "total": len(self.unenrolled_sugars)
                + self.seed_report.witness_triples_failing
                + self.seed_report.witnesses_not_dispatching_to_owner
                + opt_out_r["total"]
                + len(self.temporal_opt_outs),
            },
            "unenrolledSugars": [
                offender.to_json() for offender in self.unenrolled_sugars
            ],
            "seedHarness": self.seed_report.to_json(),
            "nonFolOptOutAudit": self.opt_out_audit.to_json(),
            "temporalOptOuts": [row.to_json() for row in self.temporal_opt_outs],
        }


EXPECTED_NON_FOL_OPT_OUTS: tuple[NonFolOptOut, ...] = (
    NonFolOptOut(
        sugar_name="AliasSugar",
        floor_name="ImportAliasValue",
        reason="import aliases record name-binding support, not a FOL claim",
    ),
    NonFolOptOut(
        sugar_name="AsyncForSugar",
        floor_name="SupportValue",
        reason=(
            "async iteration needs an async execution model before it can carry "
            "a solver verdict"
        ),
    ),
    NonFolOptOut(
        sugar_name="AsyncWithSugar",
        floor_name="SupportValue",
        reason=(
            "async context-manager execution is runtime support, not a current "
            "FOL claim"
        ),
    ),
    NonFolOptOut(
        sugar_name="AttributeAssignSugar",
        floor_name="SupportValue",
        reason=(
            "attribute mutation is stateful support until object-field updates "
            "carry a solver verdict"
        ),
        retirement_condition=(
            "retire when attribute assignment/object-field update floors emit a "
            "truthful/lying solver witness"
        ),
    ),
    NonFolOptOut(
        sugar_name="AttributeDeleteSugar",
        floor_name="SupportValue",
        reason=(
            "attribute deletion is stateful support until object-field deletes "
            "carry a solver verdict"
        ),
        retirement_condition=(
            "retire when attribute deletion/object-field delete floors emit a "
            "truthful/lying solver witness"
        ),
    ),
    NonFolOptOut(
        sugar_name="AwaitSugar",
        floor_name="SupportValue",
        reason="await unwrapping is async runtime support without a sync verdict path",
    ),
    NonFolOptOut(
        sugar_name="BitwiseOpSugar",
        floor_name="SupportValue",
        reason=(
            "bitwise terms are symbolic bitvector support until the production "
            "solver path yields a SAT/UNSAT verdict"
        ),
        retirement_condition=(
            "retire when bitwise terms produce SAT/UNSAT through the production "
            "solver path"
        ),
    ),
    NonFolOptOut(
        sugar_name="CommentSugar",
        floor_name="SupportValue",
        reason="comments are inert source support",
    ),
    NonFolOptOut(
        sugar_name="DictSugar",
        floor_name="DictLiteralValue",
        reason=(
            "dict literals are structural term support; the current solver "
            "path has no standalone dict-constructor verdict witness"
        ),
    ),
    NonFolOptOut(
        sugar_name="ExprSugar",
        floor_name="SupportValue",
        reason="expression statements evaluate for effects and leave no FOL claim",
    ),
    NonFolOptOut(
        sugar_name="ListLiteralSugar",
        floor_name="SupportValue",
        reason=(
            "default-catalog list literals are verdict-bearing through "
            "ArrayLiteralSugar; this fallback constructor is shadowed support"
        ),
    ),
    NonFolOptOut(
        sugar_name="OrdByteSugar",
        floor_name="SupportValue",
        reason=(
            "ord-byte terms are symbolic encoder support until the enclosing "
            "str.eq-bv-blocks universe carries the verdict"
        ),
        retirement_condition=(
            "retire when the enclosing str.eq-bv-blocks universe carries an "
            "OrdByte truthful/lying solver witness"
        ),
    ),
    NonFolOptOut(
        sugar_name="SubscriptAssignSugar",
        floor_name="SupportValue",
        reason="subscript assignment mutation produces no FOL assertion",
    ),
    NonFolOptOut(
        sugar_name="SubscriptDeleteSugar",
        floor_name="SupportValue",
        reason="subscript delete mutation produces no FOL assertion",
    ),
)


def seeds_from_catalog_witnesses() -> tuple[SugarWitnessSeed, ...]:
    seeds: list[SugarWitnessSeed] = []
    for claim in _catalog_claims():
        witness = _claim_witnesses(claim)
        if isinstance(witness, SugarWitnessPair):
            seeds.append(witness)
        elif isinstance(witness, tuple) and all(
            isinstance(item, SugarWitnessPair) for item in witness
        ):
            seeds.extend(witness)
    return tuple(sorted(seeds, key=lambda seed: seed.name))


def default_sugar_witness_seeds() -> tuple[SugarWitnessSeed, ...]:
    return seeds_from_catalog_witnesses()


def collect_sugar_witness_frontier(
    root: Path,
    *,
    seed_report: SugarWitnessSeedReport | None = None,
) -> SugarWitnessFrontierReport:
    _ = root
    catalog_count = len(_catalog_claims())
    if seed_report is None:
        with tempfile.TemporaryDirectory(prefix="sugar-witness-frontier-") as tmp:
            seed_report = evaluate_seed_witnesses(
                DEFAULT_SUGAR_WITNESS_SEEDS,
                Path(tmp),
                catalog_count=catalog_count,
            )
    return SugarWitnessFrontierReport(
        unenrolled_sugars=tuple(unenrolled_sugars()),
        seed_report=seed_report,
        opt_out_audit=non_fol_opt_out_audit(),
        temporal_opt_outs=temporal_opt_outs(),
    )


def unenrolled_sugars() -> tuple[UnenrolledSugar, ...]:
    return tuple(
        UnenrolledSugar(
            name=claim.name,
            module=_claim_module(claim),
            role=claim.role.value,
        )
        for claim in _catalog_claims()
        if not _claim_has_witness_or_opt_out(claim)
    )


def claim_has_witness_or_opt_out(claim) -> bool:
    return _claim_has_witness_or_opt_out(claim)


def evaluate_seed_witnesses(
    seeds: Sequence[SugarWitnessSeed],
    work_root: Path,
    *,
    catalog_count: int | None = None,
) -> SugarWitnessSeedReport:
    if catalog_count is None:
        catalog_count = len(_catalog_claims())
    triple_failures: list[WitnessTripleFailure] = []
    non_circularity_failures: list[NonCircularityFailure] = []
    for seed in seeds:
        for variant, witness in (
            ("truthful", seed.truthful),
            ("lying", seed.lying),
        ):
            result = run_source_through_real_solver(
                work_root / seed.name / variant,
                witness.source,
            )
            selected_sugars = result.selected_sugars
            if seed.owner_sugar not in selected_sugars:
                triple_failures.append(
                    WitnessTripleFailure(
                        seed=seed.name,
                        owner_sugar=seed.owner_sugar,
                        variant=variant,
                        axis="sugar-fired",
                        expected=seed.owner_sugar,
                        observed=", ".join(selected_sugars) or "<none>",
                    )
                )
                non_circularity_failures.append(
                    NonCircularityFailure(
                        seed=seed.name,
                        expected_sugar=seed.owner_sugar,
                        selected_sugars=selected_sugars,
                    )
                )
            if not result.proofir_emitted:
                triple_failures.append(
                    WitnessTripleFailure(
                        seed=seed.name,
                        owner_sugar=seed.owner_sugar,
                        variant=variant,
                        axis="proofir-emitted",
                        expected="non-empty ir",
                        observed="<empty>",
                    )
                )
            if result.verdict != witness.expected:
                triple_failures.append(
                    WitnessTripleFailure(
                        seed=seed.name,
                        owner_sugar=seed.owner_sugar,
                        variant=variant,
                        axis="verdict",
                        expected=witness.expected,
                        observed=result.verdict,
                    )
                )
    return SugarWitnessSeedReport(
        seed_count=len(seeds),
        unique_owner_count=len({seed.owner_sugar for seed in seeds}),
        catalog_count=catalog_count,
        triple_failures=tuple(triple_failures),
        non_circularity_failures=tuple(non_circularity_failures),
    )


def render_text(report: SugarWitnessFrontierReport) -> str:
    lines = ["Python sugar witness frontier\n"]
    r = report.to_json()["r"]
    lines.append(f"R(unenrolled-sugars): {r['unenrolled_sugars']}\n")
    lines.append(
        f"R(witness-triples-failing): {r['witness_triples_failing']}\n"
    )
    lines.append(
        "R(witnesses-not-dispatching-to-owner): "
        f"{r['witnesses_not_dispatching_to_owner']}\n"
    )
    lines.append(
        "R(non-fol-opt-out-drift): "
        f"{r['non_fol_opt_out_drift']}\n"
    )
    lines.append(f"R(temporal-opt-outs): {r['temporal_opt_outs']}\n")
    lines.append(
        "seed coverage: "
        f"{report.seed_report.seed_count} seed cases, "
        f"{report.seed_report.unique_owner_count}/"
        f"{report.seed_report.catalog_count} catalog sugars\n"
    )
    if report.unenrolled_sugars:
        lines.append("unenrolled sugars:\n")
        for sugar in report.unenrolled_sugars:
            lines.append(f"  - {sugar.name} ({sugar.module})\n")
    if report.seed_report.triple_failures:
        lines.append("witness triple failures:\n")
        for failure in report.seed_report.triple_failures:
            lines.append(
                f"  - {failure.seed}/{failure.variant} {failure.axis}: "
                f"expected {failure.expected}, observed {failure.observed}\n"
            )
    if report.seed_report.non_circularity_failures:
        lines.append("witnesses not dispatching to owner:\n")
        for failure in report.seed_report.non_circularity_failures:
            lines.append(
                f"  - {failure.seed}: expected {failure.expected_sugar}, "
                f"selected {', '.join(failure.selected_sugars) or '<none>'}\n"
            )
    if not report.opt_out_audit.is_zero:
        lines.append("non-FOL opt-out drift:\n")
        for row in report.opt_out_audit.pinned_but_unmarked:
            lines.append(
                f"  - pinned {row.sugar_name} -> {row.floor_name} "
                "but floor is unmarked\n"
            )
        for floor_name in report.opt_out_audit.marked_but_unpinned:
            lines.append(f"  - marked {floor_name} has no pinned sugar row\n")
    if report.temporal_opt_outs:
        lines.append("temporal opt-outs:\n")
        for row in report.temporal_opt_outs:
            lines.append(
                f"  - {row.sugar_name}: {row.retirement_condition}\n"
            )
    return "".join(lines)


def _catalog_claims():
    return tuple(sorted(default_catalog().claims, key=lambda claim: claim.name))


def current_non_fol_support_floor_names() -> set[str]:
    names: set[str] = set()
    for value in vars(floor_pkg).values():
        if isinstance(value, type) and getattr(value, "non_fol_support", False):
            names.add(value.__name__)
    return names


def non_fol_opt_out_audit(
    *,
    pinned: Sequence[NonFolOptOut] = EXPECTED_NON_FOL_OPT_OUTS,
    marked_floor_names: set[str] | None = None,
) -> NonFolOptOutAudit:
    marked = (
        current_non_fol_support_floor_names()
        if marked_floor_names is None
        else marked_floor_names
    )
    pinned_floor_names = {row.floor_name for row in pinned}
    return NonFolOptOutAudit(
        pinned_but_unmarked=tuple(
            row for row in pinned if row.floor_name not in marked
        ),
        marked_but_unpinned=tuple(sorted(marked - pinned_floor_names)),
    )


def temporal_opt_outs(
    *,
    pinned: Sequence[NonFolOptOut] = EXPECTED_NON_FOL_OPT_OUTS,
) -> tuple[NonFolOptOut, ...]:
    return tuple(row for row in pinned if row.retirement_condition is not None)


def _claim_module(claim) -> str:
    return getattr(claim.build, "__module__", "<unknown>")


def _claim_witnesses(claim) -> object:
    if claim.witnesses is None:
        raise TypeError(f"{claim.name} registered without witnesses()")
    return claim.witnesses()


def _claim_has_witness_or_opt_out(claim) -> bool:
    witness = _claim_witnesses(claim)
    if isinstance(witness, SugarWitnessPair):
        return True
    if isinstance(witness, tuple) and witness and all(
        isinstance(item, SugarWitnessPair) for item in witness
    ):
        return True
    if isinstance(witness, NotVerdictBearing):
        pinned = _non_fol_opt_out_for(claim.name)
        return (
            pinned is not None
            and witness.sugar_name == pinned.sugar_name
            and witness.floor_name == pinned.floor_name
            and witness.reason == pinned.reason
        )
    return False


def _non_fol_opt_out_for(sugar_name: str) -> NonFolOptOut | None:
    for row in EXPECTED_NON_FOL_OPT_OUTS:
        if row.sugar_name == sugar_name:
            return row
    return None


DEFAULT_SUGAR_WITNESS_SEEDS: tuple[SugarWitnessSeed, ...] = (
    default_sugar_witness_seeds()
)
