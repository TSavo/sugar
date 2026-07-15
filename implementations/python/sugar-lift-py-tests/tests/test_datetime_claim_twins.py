from __future__ import annotations

import ast
from pathlib import Path

import pytest

from claim_mass_corpus import AssertionClaim, DATETIME_CLAIMS, assertion_claims
from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.witness_harness import (
    WitnessPipelineResult,
    run_source_through_real_solver,
)

VENDOR = Path(__file__).parent / "vendor" / "cpython-3.11" / "datetime.py"


def test_datetime_claim_identity_survives_line_movement() -> None:
    source = VENDOR.read_text(encoding="utf-8")
    shifted = assertion_claims("\n\n" + source, filename=str(VENDOR))

    assert [(claim.cid, claim.owner) for claim in shifted] == [
        (claim.cid, claim.owner) for claim in DATETIME_CLAIMS
    ]
    assert [claim.line for claim in shifted] == [
        claim.line + 2 for claim in DATETIME_CLAIMS
    ]


def _negate_assertion(source: str, line: int) -> str:
    tree = ast.parse(source, filename=str(VENDOR))
    assertion = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assert) and node.lineno == line
    )
    assert assertion.lineno == assertion.end_lineno
    rows = source.splitlines(keepends=True)
    row = rows[line - 1]
    start = assertion.test.col_offset
    end = assertion.test.end_col_offset
    row = f"{row[:start]}not ({row[start:end]}){row[end:]}"
    rows[line - 1] = row
    return "".join(rows)


@pytest.fixture(scope="module")
def truthful_datetime_verdict(
    tmp_path_factory: pytest.TempPathFactory,
) -> WitnessPipelineResult:
    source = VENDOR.read_text(encoding="utf-8")
    project = tmp_path_factory.mktemp("datetime-truthful")
    result = run_source_through_real_solver(project, source)
    assert result.verdict == "sat", _verdict_failure("truthful", None, result)
    assert result.proofir_emitted
    assertions = _assertion_accounting(source, project, result)
    assert assertions["lifted_cited"] == len(DATETIME_CLAIMS)
    assert assertions["refused_loud"] == 0
    assert assertions["silently_unaccounted"] == 0
    return result


@pytest.mark.parametrize(
    "claim", DATETIME_CLAIMS, ids=lambda claim: claim.cid.removeprefix("sha256:")[:12]
)
def test_datetime_claim_twins_reach_real_sat_unsat_verdicts(
    claim: AssertionClaim,
    tmp_path: Path,
    truthful_datetime_verdict: WitnessPipelineResult,
) -> None:
    """Every cited datetime fact remains a claim and its exact twin is UNSAT."""
    line = claim.line
    source = _negate_assertion(VENDOR.read_text(encoding="utf-8"), line)
    project = tmp_path / f"datetime-lie-{line}"
    result = run_source_through_real_solver(project, source)
    assertions = _assertion_accounting(source, project, result)

    lifted_lines = {locus["line"] for locus in assertions["lifted_loci"]}
    refused_lines = {locus["line"] for locus in assertions["refused_loci"]}
    assert line in lifted_lines, (
        f"datetime.py:{line} claim={claim.cid} owner={claim.owner} evaded the "
        "referee: its negated twin was not emitted "
        "as a cited ProofIR claim; replacement=keep the assertion lifted and let "
        "the solver return UNSAT"
    )
    assert line not in refused_lines
    assert assertions["silently_unaccounted"] == 0
    assert result.verdict == "unsat", _verdict_failure("lying", line, result)


def _assertion_accounting(
    source: str, project: Path, result: WitnessPipelineResult
) -> dict:
    filename = str((project / "test_witness.py").resolve())
    return account_lift_coverage(
        census_source(source, file=filename), result.lift_doc
    ).to_json()["assertions"]


def _verdict_failure(kind: str, line: int | None, result: WitnessPipelineResult) -> str:
    rows = result.prove_doc.get("rows", [])
    return (
        f"datetime {kind} twin line={line} verdict={result.verdict}; "
        f"statuses={[row.get('status') for row in rows]}; "
        f"reasons={[row.get('reason') for row in rows]}; "
        "replacement=emit every cited datetime assertion through ProofIR so the "
        "truthful corpus is SAT and each exact negation is UNSAT"
    )
