from __future__ import annotations

import concurrent.futures
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from sugar_lift_py_tests import floor as floor_pkg
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.sugar.witnesses import (
    EffectWitnessSource,
    NotVerdictBearing,
    SugarRedEffectWitnessPair,
    SugarWitnessPair,
)
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver
from sugar_lift_py_tests.witness_harness import ensure_sugar_bin


@dataclass(frozen=True)
class UnenrolledSugar:
    name: str
    module: str
    role: str

    def to_json(self) -> dict[str, Any]:
        return {"name": self.name, "module": self.module, "role": self.role}


SugarWitnessSeed = SugarWitnessPair | SugarRedEffectWitnessPair


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
                "total": len(self.pinned_but_unmarked) + len(self.marked_but_unpinned),
            },
            "pinnedButUnmarked": [row.to_json() for row in self.pinned_but_unmarked],
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
class RedEffectObservation:
    effect_class: str
    reason: str
    selected_sugars: tuple[str, ...]


@dataclass(frozen=True)
class SeedWitnessEvaluation:
    seed_name: str
    triple_failures: tuple[WitnessTripleFailure, ...]
    non_circularity_failures: tuple[NonCircularityFailure, ...]


class SeedWitnessEvaluationError(RuntimeError):
    pass


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
            "tripleFailures": [failure.to_json() for failure in self.triple_failures],
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
                "witness_triples_failing": (self.seed_report.witness_triples_failing),
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
        retirement_condition=(
            "retire when module import alias support is emitted as a "
            "factory-walk owner row and a consuming alias-backed assertion can "
            "witness that owner; current default proof path calls "
            "factory/build.py:87 _build_source_report before SourceFragmentStack "
            "dispatch, then factory/literal_call_report.py:304 reads imports as "
            "_import_bindings resolver metadata, while sugar/alias_sugar.py:18 "
            "can own only an observed alias fragment, so alias-backed proof probes "
            "select CallSugar/PrimitiveLiteralSugar and no AliasSugar owner"
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
        retirement_condition=(
            "until dict-constructor equality carries a verdict witness "
            "through the solver path (assert {1:2} == {1:3} is a "
            "verdict-bearing claim; current probes select DictSugar and "
            "refuse at DictLiteralValue.project_callsite_with, while the "
            "structural-identity tests already prove the twin is "
            "constructible the moment that bridge exists)"
        ),
    ),
    NonFolOptOut(
        sugar_name="DictCompSugar",
        floor_name="DictLiteralValue",
        reason=(
            "dict comprehensions reduce to structural dict support; "
            "dict-constructor equality is not currently a standalone solver verdict"
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
        retirement_condition=(
            "retire when shadowed fallback sugars have a typed delegated-owner "
            "witness seat, or the default catalog can select ListLiteralSugar "
            "without stealing ArrayLiteralSugar's verdict-bearing claim; "
            "claim/sugar_catalog.py:15 admits both List owners, factory/build.py:174 "
            "selects the candidate that dominates by comes_before, and "
            "sugar/array_literal_sugar.py:29 declares "
            "comes_before=('ListLiteralSugar',) over the same observed List shape "
            "that sugar/list_literal_sugar.py:28 owns, so production probes "
            "select ArrayLiteralSugar instead of ListLiteralSugar"
        ),
    ),
    NonFolOptOut(
        sugar_name="PassSugar",
        floor_name="SupportValue",
        reason="pass is inert control-flow support",
    ),
    NonFolOptOut(
        sugar_name="SetCompSugar",
        floor_name="SetLiteralValue",
        reason=(
            "set comprehensions reduce to structural set support; "
            "set-constructor equality is not currently a standalone solver verdict"
        ),
    ),
    NonFolOptOut(
        sugar_name="SetSugar",
        floor_name="SetLiteralValue",
        reason=(
            "set literals are structural term support; set-constructor equality "
            "is not currently a standalone solver verdict"
        ),
    ),
)


def seeds_from_catalog_witnesses() -> tuple[SugarWitnessSeed, ...]:
    seeds: list[SugarWitnessSeed] = []
    for claim in _catalog_claims():
        witness = _claim_witnesses(claim)
        seeds.extend(_witness_pairs(witness))
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
    ordered_items = tuple(
        sorted(enumerate(seeds), key=lambda item: (item[1].name, item[0]))
    )
    catalog_names: set[str] | None = None
    if catalog_count is None:
        claims = _catalog_claims()
        catalog_count = len(claims)
        catalog_names = {claim.name for claim in claims}
    evaluations = _evaluate_seed_witnesses_ordered(ordered_items, work_root)
    triple_failures = [
        failure for evaluation in evaluations for failure in evaluation.triple_failures
    ]
    non_circularity_failures = [
        failure
        for evaluation in evaluations
        for failure in evaluation.non_circularity_failures
    ]
    return SugarWitnessSeedReport(
        seed_count=len(seeds),
        unique_owner_count=len(_seed_coverage_owner_names(seeds, catalog_names)),
        catalog_count=catalog_count,
        triple_failures=tuple(triple_failures),
        non_circularity_failures=tuple(non_circularity_failures),
    )


def _evaluate_seed_witnesses_ordered(
    ordered_items: Sequence[tuple[int, SugarWitnessSeed]],
    work_root: Path,
) -> tuple[SeedWitnessEvaluation, ...]:
    if not ordered_items:
        return ()
    workers = _seed_witness_worker_count(len(ordered_items))
    if any(
        not isinstance(seed, SugarRedEffectWitnessPair) for _, seed in ordered_items
    ):
        ensure_sugar_bin()
    if workers == 1 or len(ordered_items) == 1:
        return tuple(_evaluate_one_seed(seed, work_root) for _, seed in ordered_items)

    results: dict[tuple[int, str], SeedWitnessEvaluation] = {}
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=workers,
        thread_name_prefix="sugar-witness-seed",
    ) as executor:
        future_by_key = {
            executor.submit(_evaluate_one_seed, seed, work_root): (index, seed)
            for index, seed in ordered_items
        }
        for future in concurrent.futures.as_completed(future_by_key):
            index, seed = future_by_key[future]
            try:
                results[(index, seed.name)] = future.result()
            except SeedWitnessEvaluationError:
                raise
            except BaseException as exc:
                raise SeedWitnessEvaluationError(
                    "seed witness worker crashed before variant context: "
                    f"seed={seed.name} owner={seed.owner_sugar}: {exc}"
                ) from exc
    return tuple(results[(index, seed.name)] for index, seed in ordered_items)


def _seed_witness_worker_count(seed_count: int) -> int:
    if seed_count <= 1:
        return 1
    raw = os.environ.get("SUGAR_WITNESS_WORKERS")
    if raw is not None:
        try:
            workers = int(raw)
        except ValueError as exc:
            raise ValueError(
                "invalid SUGAR_WITNESS_WORKERS: expected positive integer, "
                f"observed {raw!r}"
            ) from exc
        if workers < 1:
            raise ValueError(
                "invalid SUGAR_WITNESS_WORKERS: expected positive integer, "
                f"observed {raw!r}"
            )
        return min(workers, seed_count)
    return min(8, os.cpu_count() or 1, seed_count)


def _evaluate_one_seed(
    seed: SugarWitnessSeed,
    work_root: Path,
) -> SeedWitnessEvaluation:
    triple_failures: list[WitnessTripleFailure] = []
    non_circularity_failures: list[NonCircularityFailure] = []
    if isinstance(seed, SugarRedEffectWitnessPair):
        for variant, witness in (
            ("truthful", seed.truthful),
            ("lying", seed.lying),
        ):
            try:
                observation = _observe_red_effect(witness)
            except BaseException as exc:
                raise SeedWitnessEvaluationError(
                    "seed witness worker crashed: "
                    f"seed={seed.name} variant={variant} "
                    f"owner={seed.owner_sugar}: {exc}"
                ) from exc
            _check_owner_selected(
                seed=seed,
                variant=variant,
                selected_sugars=observation.selected_sugars,
                triple_failures=triple_failures,
                non_circularity_failures=non_circularity_failures,
            )
            _check_red_effect_witness(
                seed=seed,
                variant=variant,
                witness=witness,
                observation=observation,
                failures=triple_failures,
            )
        return SeedWitnessEvaluation(
            seed_name=seed.name,
            triple_failures=tuple(triple_failures),
            non_circularity_failures=tuple(non_circularity_failures),
        )

    for variant, witness in (
        ("truthful", seed.truthful),
        ("lying", seed.lying),
    ):
        try:
            result = run_source_through_real_solver(
                work_root / seed.name / variant,
                witness.source,
            )
        except BaseException as exc:
            raise SeedWitnessEvaluationError(
                "seed witness worker crashed: "
                f"seed={seed.name} variant={variant} "
                f"owner={seed.owner_sugar}: {exc}"
            ) from exc
        _check_owner_selected(
            seed=seed,
            variant=variant,
            selected_sugars=result.selected_sugars,
            triple_failures=triple_failures,
            non_circularity_failures=non_circularity_failures,
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
    return SeedWitnessEvaluation(
        seed_name=seed.name,
        triple_failures=tuple(triple_failures),
        non_circularity_failures=tuple(non_circularity_failures),
    )


def _check_owner_selected(
    *,
    seed: SugarWitnessSeed,
    variant: str,
    selected_sugars: tuple[str, ...],
    triple_failures: list[WitnessTripleFailure],
    non_circularity_failures: list[NonCircularityFailure],
) -> None:
    if seed.owner_sugar in selected_sugars:
        return
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


def _observe_red_effect(witness: EffectWitnessSource) -> RedEffectObservation:
    from sugar_lift_py_tests.claim import SugarRole
    from sugar_lift_py_tests.context import FactoryBuildContext
    from sugar_lift_py_tests.effect import effect_kind, effect_reason
    from sugar_lift_py_tests.factory import FactoryGap
    from sugar_lift_py_tests.factory.build import build_node
    from sugar_lift_py_tests.factory.source_fragment import SourceFragment
    from sugar_lift_py_tests.floor import SymbolicValue
    from sugar_lift_py_tests.ir import make_var
    from sugar_lift_py_tests.outcome import Incomplete
    from sugar_lift_py_tests.sugar_body import SugarBody
    from sugar_lift_py_tests.temporal import bind_temporal

    module = SourceFragment.from_source(witness.source, "test_witness.py")
    function = next(
        fragment
        for fragment in module.walk()
        if fragment.observed in {"FunctionDef", "AsyncFunctionDef"}
        and fragment.function_name() == witness.function_name
    )
    audit_sink: list[dict[str, Any]] = []
    ctx = FactoryBuildContext(
        filename="test_witness.py",
        catalog=default_catalog(),
        audit_sink=audit_sink,
    )
    for arg in function.function_params():
        ctx = bind_temporal(
            ctx,
            arg,
            SymbolicValue(make_var(arg)),
            owner="SugarWitnessInstruments",
            blame=function.blame,
        )
    try:
        result = build_node(
            function.function_body_block(),
            filename="test_witness.py",
            role=SugarRole.STATEMENT,
            ctx=ctx,
        )
        outcome = SugarBody(
            sugar=result.sugar,
            role=SugarRole.STATEMENT,
            audit_row=result.audit_row,
        ).reduce(ctx)
    except FactoryGap as exc:
        return RedEffectObservation(
            effect_class="FactoryGap",
            reason=str(exc),
            selected_sugars=_selected_sugars_from_audit(audit_sink),
        )
    if isinstance(outcome, Incomplete):
        return RedEffectObservation(
            effect_class=effect_kind(outcome.effect),
            reason=effect_reason(outcome.effect),
            selected_sugars=_selected_sugars_from_audit(audit_sink),
        )
    return RedEffectObservation(
        effect_class="<green>",
        reason=repr(outcome),
        selected_sugars=_selected_sugars_from_audit(audit_sink),
    )


def _selected_sugars_from_audit(rows: Sequence[dict[str, Any]]) -> tuple[str, ...]:
    selected: list[str] = []
    seen: set[str] = set()
    for row in rows:
        name = row.get("selected")
        if not isinstance(name, str) or name in seen:
            continue
        seen.add(name)
        selected.append(name)
    return tuple(selected)


def _check_red_effect_witness(
    *,
    seed: SugarRedEffectWitnessPair,
    variant: str,
    witness: EffectWitnessSource,
    observation: RedEffectObservation,
    failures: list[WitnessTripleFailure],
) -> None:
    expectation = witness.expectation
    matched = (
        observation.effect_class == expectation.effect_class
        and expectation.reason_needle in observation.reason
        and expectation.blame_needle in observation.reason
    )
    if matched == witness.expected_match:
        return
    expected = (
        f"{'match' if witness.expected_match else 'reject'} "
        f"{expectation.effect_class} reason~={expectation.reason_needle!r} "
        f"blame~={expectation.blame_needle!r}"
    )
    observed = f"{observation.effect_class}: {observation.reason}"
    failures.append(
        WitnessTripleFailure(
            seed=seed.name,
            owner_sugar=seed.owner_sugar,
            variant=variant,
            axis="typed-red-effect",
            expected=expected,
            observed=observed,
        )
    )


def render_text(report: SugarWitnessFrontierReport) -> str:
    lines = ["Python sugar witness frontier\n"]
    r = report.to_json()["r"]
    lines.append(f"R(unenrolled-sugars): {r['unenrolled_sugars']}\n")
    lines.append(f"R(witness-triples-failing): {r['witness_triples_failing']}\n")
    lines.append(
        "R(witnesses-not-dispatching-to-owner): "
        f"{r['witnesses_not_dispatching_to_owner']}\n"
    )
    lines.append("R(non-fol-opt-out-drift): " f"{r['non_fol_opt_out_drift']}\n")
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
            lines.append(f"  - {row.sugar_name}: {row.retirement_condition}\n")
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


def _seed_coverage_owner_names(
    seeds: Sequence[SugarWitnessSeed],
    catalog_names: set[str] | None,
) -> set[str]:
    owners = {seed.owner_sugar for seed in seeds}
    if catalog_names is None:
        return owners
    return owners | {
        row.sugar_name for row in temporal_opt_outs() if row.sugar_name in catalog_names
    }


def _claim_module(claim) -> str:
    return getattr(claim.build, "__module__", "<unknown>")


def _claim_witnesses(claim) -> object:
    if claim.witnesses is None:
        raise TypeError(f"{claim.name} registered without witnesses()")
    return claim.witnesses()


def _claim_has_witness_or_opt_out(claim) -> bool:
    witness = _claim_witnesses(claim)
    if _witness_pairs(witness):
        return True
    opt_out = _not_verdict_bearing(witness)
    if opt_out is not None:
        pinned = _non_fol_opt_out_for(claim.name)
        return (
            pinned is not None
            and opt_out.sugar_name == pinned.sugar_name
            and opt_out.floor_name == pinned.floor_name
            and opt_out.reason == pinned.reason
        )
    return False


def _witness_pairs(witness: object) -> tuple[SugarWitnessSeed, ...]:
    if isinstance(witness, (SugarWitnessPair, SugarRedEffectWitnessPair)):
        return (witness,)
    if isinstance(witness, tuple):
        return tuple(
            item
            for item in witness
            if isinstance(item, (SugarWitnessPair, SugarRedEffectWitnessPair))
        )
    return ()


def _not_verdict_bearing(witness: object) -> NotVerdictBearing | None:
    if isinstance(witness, NotVerdictBearing):
        return witness
    if isinstance(witness, tuple):
        for item in witness:
            if isinstance(item, NotVerdictBearing):
                return item
    return None


def _non_fol_opt_out_for(sugar_name: str) -> NonFolOptOut | None:
    for row in EXPECTED_NON_FOL_OPT_OUTS:
        if row.sugar_name == sugar_name:
            return row
    return None


DEFAULT_SUGAR_WITNESS_SEEDS: tuple[SugarWitnessSeed, ...] = (
    default_sugar_witness_seeds()
)
