from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.witness_harness import (
    Verdict,
    run_source_through_real_solver,
)


@dataclass(frozen=True)
class UnenrolledSugar:
    name: str
    module: str
    role: str

    def to_json(self) -> dict[str, Any]:
        return {"name": self.name, "module": self.module, "role": self.role}


@dataclass(frozen=True)
class WitnessSource:
    source: str
    expected: Verdict


@dataclass(frozen=True)
class SugarWitnessSeed:
    name: str
    owner_sugar: str
    family: str
    truthful: WitnessSource
    lying: WitnessSource


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

    @property
    def is_zero(self) -> bool:
        return not self.unenrolled_sugars and self.seed_report.is_zero

    def to_json(self) -> dict[str, Any]:
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
                "total": len(self.unenrolled_sugars)
                + self.seed_report.witness_triples_failing
                + self.seed_report.witnesses_not_dispatching_to_owner,
            },
            "unenrolledSugars": [
                offender.to_json() for offender in self.unenrolled_sugars
            ],
            "seedHarness": self.seed_report.to_json(),
        }


DEFAULT_SUGAR_WITNESS_SEEDS: tuple[SugarWitnessSeed, ...] = (
    SugarWitnessSeed(
        name="slice_callsite",
        owner_sugar="CallSugar",
        family="slice/subscript",
        truthful=WitnessSource(
            source=(
                "def A():\n"
                "    return 'abcdef'[1:3]\n"
                "\n"
                "def test_a():\n"
                "    assert A() == 'bc'\n"
            ),
            expected="sat",
        ),
        lying=WitnessSource(
            source=(
                "def A():\n"
                "    return 'abcdef'[1:3]\n"
                "\n"
                "def test_a():\n"
                "    assert A() == 'zz'\n"
            ),
            expected="unsat",
        ),
    ),
    SugarWitnessSeed(
        name="binary_dunder_callsite",
        owner_sugar="CallSugar",
        family="binary-dunder",
        truthful=WitnessSource(
            source=(
                "class X:\n"
                "    def __init__(self, y):\n"
                "        self.x = y\n"
                "    def __add__(self, other):\n"
                "        return other.x\n"
                "def A():\n"
                "    return [10, 20, 30][X(0) + X(1)]\n"
                "def test_a():\n"
                "    assert A() == 20\n"
            ),
            expected="sat",
        ),
        lying=WitnessSource(
            source=(
                "class X:\n"
                "    def __init__(self, y):\n"
                "        self.x = y\n"
                "    def __add__(self, other):\n"
                "        return other.x\n"
                "def A():\n"
                "    return [10, 20, 30][X(0) + X(1)]\n"
                "def test_a():\n"
                "    assert A() == 10\n"
            ),
            expected="unsat",
        ),
    ),
    SugarWitnessSeed(
        name="literal_call_return",
        owner_sugar="ReturnSugar",
        family="literal-call",
        truthful=WitnessSource(
            source=(
                "def A(x):\n"
                "    return x + 1\n"
                "\n"
                "def test_a():\n"
                "    assert A(5) == 6\n"
            ),
            expected="sat",
        ),
        lying=WitnessSource(
            source=(
                "def A(x):\n"
                "    return x + 1\n"
                "\n"
                "def test_a():\n"
                "    assert A(5) == 7\n"
            ),
            expected="unsat",
        ),
    ),
    SugarWitnessSeed(
        name="try_body",
        owner_sugar="TrySugar",
        family="try",
        truthful=WitnessSource(
            source=(
                "def wrapped(x):\n"
                "    try:\n"
                "        return x + 1\n"
                "    except Exception:\n"
                "        return 99\n"
                "\n"
                "def test_wrapped():\n"
                "    assert wrapped(5) == 6\n"
            ),
            expected="sat",
        ),
        lying=WitnessSource(
            source=(
                "def wrapped(x):\n"
                "    try:\n"
                "        return x + 1\n"
                "    except Exception:\n"
                "        return 99\n"
                "\n"
                "def test_wrapped():\n"
                "    assert wrapped(5) == 7\n"
            ),
            expected="unsat",
        ),
    ),
)


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
    return "".join(lines)


def _catalog_claims():
    return tuple(sorted(default_catalog().claims, key=lambda claim: claim.name))


def _claim_module(claim) -> str:
    return getattr(claim.build, "__module__", "<unknown>")


def _claim_has_witness_or_opt_out(claim) -> bool:
    owner = getattr(claim.build, "__self__", None)
    if owner is None:
        return False
    owner_dict = getattr(owner, "__dict__", {})
    return "witnesses" in owner_dict or "not_verdict_bearing" in owner_dict
