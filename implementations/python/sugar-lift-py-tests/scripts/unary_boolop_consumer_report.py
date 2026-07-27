#!/usr/bin/env python3
"""Emit #6516 testimony for the authenticated UnaryOp/BoolOp drain."""

from __future__ import annotations

import platform
from pathlib import Path
import subprocess
import tempfile

from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
from sugar_lift_py_tests.consumer_resolution_report import (
    BinaryCellTestimony,
    CallerAttribution,
    CallerReportTestimony,
    ConsumerResolutionRequest,
    DemandTableCellTestimony,
    LauncherSelectionTestimony,
    print_consumer_hit,
)
from sugar_lift_py_tests.demand_table_identity import DemandTableIdentityV1
from sugar_lift_py_tests.no_call_body_attribution import (
    AUTHENTICATED_RUNTIME,
    CANONICAL_CORPUS_MANIFEST_CID,
    SHARED_DEMAND_TABLE_CONTENT_KEY,
    AttributionOutcome,
    ProducerFamily,
    attribute_body_probes,
    discover_no_call_body_probes,
    pull_shared_demand_table,
    require_expected_denominators,
)


def _checked_stdout(command: tuple[str, ...], *, cwd: Path) -> str:
    completed = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"authenticated command failed exit={completed.returncode}: "
            f"{completed.stderr.strip()[:400]}"
        )
    return completed.stdout.strip()


def main() -> int:
    repo_root = Path(__file__).resolve().parents[4]
    sugarbin = repo_root / "bin" / "sugarbin"
    source_stamp = _checked_stdout(
        (str(sugarbin), "--print-source-stamp"), cwd=repo_root
    )
    binary_path = _checked_stdout((str(sugarbin),), cwd=repo_root)
    if not Path(binary_path).is_file():
        raise RuntimeError("sugarbin did not select a verified binary file")

    machine = platform.machine().lower()
    if machine == "amd64":
        machine = "x86_64"
    platform_key = f"{platform.system().lower()}-{machine}"
    profile = "release"

    corpus = authenticated_pandas_corpus()
    with tempfile.TemporaryDirectory() as scratch:
        payload = pull_shared_demand_table(
            repo_root, Path(scratch) / "python-demand-table.json"
        )
    families = frozenset((ProducerFamily.UNARYOP, ProducerFamily.BOOLOP))
    probes = require_expected_denominators(
        discover_no_call_body_probes(payload, corpus.root, families=families),
        families=families,
    )
    attribution = attribute_body_probes(probes)
    unary = attribution.by_family[ProducerFamily.UNARYOP]
    boolop = attribution.by_family[ProducerFamily.BOOLOP]
    if (
        unary.enrolled != 13
        or unary.named_refusals != 11
        or unary.reattributions != 2
        or unary.construction_panics != 0
        or boolop.enrolled != 2
        or boolop.named_refusals != 2
        or boolop.reattributions != 0
        or boolop.construction_panics != 0
    ):
        raise RuntimeError(
            f"unexpected authenticated attribution: {attribution.render()}"
        )

    identity_payload = payload["identity"]
    identity = DemandTableIdentityV1(
        content_key=payload["contentKey"],
        corpus_manifest_cid=identity_payload["corpusManifestCid"],
        schema_version=identity_payload["schemaVersion"],
        producer_source_cid=identity_payload["producerSourceCid"],
        resolution_config_cid=identity_payload["resolutionConfigCid"],
        parser_identity=identity_payload["parserIdentity"],
        file_count=identity_payload["fileCount"],
    )
    request = ConsumerResolutionRequest(
        source_stamp=source_stamp,
        runtime=AUTHENTICATED_RUNTIME,
        platform=platform_key,
        profile=profile,
        corpus_manifest_cid=CANONICAL_CORPUS_MANIFEST_CID,
        corpus_files=corpus.file_count,
    )
    binary = BinaryCellTestimony(
        source_stamp=source_stamp,
        platform=platform_key,
        profile=profile,
        binary_name=Path(binary_path).name,
        artifact_verified=True,
    )
    demand = DemandTableCellTestimony(
        identity=identity,
        runtime=AUTHENTICATED_RUNTIME,
        platform=platform_key,
        profile=profile,
        artifact_verified=True,
    )
    launcher = LauncherSelectionTestimony(
        runtime=AUTHENTICATED_RUNTIME,
        corpus_manifest_cid=CANONICAL_CORPUS_MANIFEST_CID,
        corpus_files=corpus.file_count,
        selected_binary_source_stamp=source_stamp,
        selected_binary_platform=platform_key,
        selected_binary_profile=profile,
        selected_demand_content_key=SHARED_DEMAND_TABLE_CONTENT_KEY,
        selected_demand_runtime=AUTHENTICATED_RUNTIME,
        selected_demand_platform=platform_key,
        selected_demand_profile=profile,
        artifact_verification_succeeded=True,
    )
    caller = CallerReportTestimony(
        concrete_source_site="pandas/tests/extension/base/ops.py:258:16 (~ser)",
        before_outcome="construction-panic:bitwise_invert",
        after_outcome="named-refusal:unary_operation_exception_floor",
        surviving=(
            CallerAttribution(
                AttributionOutcome.NAMED_REFUSAL,
                "unary_operation_exception_floor",
            ),
        ),
    )
    print_consumer_hit(request, binary, demand, launcher, caller)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
