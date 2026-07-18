"""The report door recovers a loud cell only as mandatory red evidence."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pytest

from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.idd.collect_panic_audit import (
    _hermetic_env_for_sugar_command,
    _prepare_audit_workspace,
)
from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.kit_rpc.factory_walk_row_dto import FactoryWalkRedRowDto
from sugar_lift_py_tests.kit_rpc.recovered_audit_dto import RecoveredAuditDto
from sugar_lift_py_tests.lift_rpc import audit_lift_file, lift_file_payload

_SOURCE = """\
def test_broken(x):
    assert isinstance(x, UnknownLocal)

def enc(x):
    if x == "ccc":
        return "yyy"
    return x

def test_enc():
    assert enc("ccc") == "yyy"
"""


def test_report_recovers_unknown_local_isinstance_as_red_and_keeps_clean_fact() -> None:
    """One loud definition cannot erase an independent completed definition."""
    payload = lift_file_payload(_SOURCE, "frontier.py")
    rpc = payload.to_rpc()

    facts = [
        row
        for row in rpc["ir"]
        if isinstance(row, dict) and str(row.get("name", "")).endswith("::assertion")
    ]
    assert len(facts) == 1
    assert facts[0]["sourceWarrants"][0]["span"]["start_line"] == 10
    assert rpc["effects"] == []

    red = [row for row in payload.factory_walk if isinstance(row, FactoryWalkRedRowDto)]
    unknown = [row for row in red if row.ast_kind == "UnknownLocal"]
    assert len(unknown) == 1
    row = unknown[0]
    assert row.status.value == "unclassified"
    assert row.line == 2
    assert "owner=TemporalContext" in row.reason
    assert "observed=UnknownLocal" in row.reason
    assert row.to_rpc()["status"] == "unresolved"
    assert row.to_rpc()["verdict"] == "gap"

    summary = rpc["factoryAuditSummary"]
    assert summary["statusCounts"]["unresolved"] == 1
    assert summary["unresolvedSites"][0]["ast_kind"] == "UnknownLocal"

    axis = account_lift_coverage(
        census_source(_SOURCE, file="frontier.py"), rpc
    ).to_json()["assertions"]
    assert axis["stated"] == 2
    assert axis["lifted_cited"] == 1
    assert axis["refused_loud"] == 0
    assert axis["silently_unaccounted"] == 1
    assert axis["is_zero"] is False
    assert axis["silent_loci"][0]["status"] == "recovered-factory-panic"


def test_direct_audit_stays_fail_fast_and_recovered_audit_stays_proofir_free() -> None:
    """Report recovery does not weaken either audit contract."""
    with pytest.raises(
        FactoryPanic,
        match=r"owner=TemporalContext.*observed=UnknownLocal",
    ):
        audit_lift_file(_SOURCE, "frontier.py")

    recovered = audit_lift_file(
        _SOURCE,
        "frontier.py",
        recover_panics=True,
    )
    assert isinstance(recovered, RecoveredAuditDto)
    assert len(recovered.panics) == 1
    assert recovered.panics[0].gap["observed"] == "UnknownLocal"
    assert "ir" not in recovered.to_rpc()


def _run_report_witness(
    *,
    tmp_path: Path,
    source: str,
    sugar_binary: str,
) -> subprocess.CompletedProcess[str]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    source_file = tmp_path / "source.py"
    source_file.write_text(source, encoding="utf-8")
    workspace = tmp_path / "workspace"
    repo_root = Path(__file__).resolve().parents[4]
    _prepare_audit_workspace(source_file, repo_root, workspace, audit_only=False)
    command = [sugar_binary, "lift", "--report", "--json", os.fspath(workspace)]
    return subprocess.run(
        command,
        cwd=repo_root,
        env=_hermetic_env_for_sugar_command(command),
        text=True,
        capture_output=True,
        check=False,
    )


def test_report_verdict_witness_loud_truthful_red_covered_twin_green(
    tmp_path: Path,
    sugar_binary_handoff: str,
) -> None:
    """The report may render a panic, but may never swallow its red verdict."""
    truthful = _run_report_witness(
        tmp_path=tmp_path / "truthful",
        source=_SOURCE,
        sugar_binary=sugar_binary_handoff,
    )
    assert truthful.returncode != 0
    truthful_report = json.loads(truthful.stdout)
    truthful_red = [
        row
        for row in truthful_report["factoryWalk"]
        if row.get("status") == "unresolved"
    ]
    assert len(truthful_red) == 1
    assert truthful_red[0]["ast_kind"] == "UnknownLocal"
    assert truthful_report["liftCoverage"]["assertions"]["silently_unaccounted"] == 1
    assert "enc#euf#" in truthful.stdout

    covered_twin = _run_report_witness(
        tmp_path=tmp_path / "covered-twin",
        source=_SOURCE.replace("UnknownLocal", "int"),
        sugar_binary=sugar_binary_handoff,
    )
    assert covered_twin.returncode == 0, covered_twin.stderr
    covered_report = json.loads(covered_twin.stdout)
    assert not [
        row
        for row in covered_report["factoryWalk"]
        if row.get("status") == "unresolved"
    ]
    assert covered_report["liftCoverage"]["assertions"]["silently_unaccounted"] == 0
