#!/usr/bin/env python3
"""Refuse before the pandas scoreboard unless launch identity is complete."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable

# This script is the owning launcher for a synced source-tree measurement.  Its
# Python imports must therefore resolve from that exact checkout, never from an
# image-global package that happens to share the name.  Seat the three in-repo
# packages before importing any of them below.
_REPO = Path(__file__).resolve().parents[4]
_SOURCE_ROOTS = tuple(
    _REPO / "implementations/python" / package / "src"
    for package in (
        "sugar-lift-py-tests",
        "sugar-lift-python-source",
        "sugar-source-tree",
    )
)
for _source_root in reversed(_SOURCE_ROOTS):
    sys.path.insert(0, str(_source_root))

from sugar_lift_py_tests.authenticated_pytest import (
    ExecutionEnvironmentMismatch,
    authenticated_pandas_corpus,
    interpreter_identity,
)
from sugar_lift_py_tests.corpus_pin import load_pin, pin_corpus, require_pin

EX_CONFIG = 78
EX_IOERR = 74
TERMINAL_ARTIFACTS = (
    "recensus.json",
    "measurement-status.txt",
    "lease-record.json",
)


def require_synced_source_packages(repo: Path) -> dict[str, str]:
    """Authenticate every Python package used by the census to this checkout."""
    import sugar_lift_py_tests
    import sugar_lift_python_source
    import sugar_source_tree

    observed = {
        "sugar_lift_py_tests": Path(sugar_lift_py_tests.__file__).resolve(),
        "sugar_lift_python_source": Path(sugar_lift_python_source.__file__).resolve(),
        "sugar_source_tree": Path(sugar_source_tree.__file__).resolve(),
    }
    source_root = (repo / "implementations/python").resolve()
    for name, path in observed.items():
        if source_root not in path.parents:
            raise ExecutionEnvironmentMismatch(
                f"census package {name} resolved outside synced checkout: {path}"
            )
    return {name: str(path) for name, path in observed.items()}


@dataclass(frozen=True)
class CensusLaunch:
    commit: str
    repo: Path
    corpus_root: Path
    pin: Path
    output: Path

def require_launch_coordinates(commit: str, mount_proof: str, output: Path) -> None:
    if len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit):
        raise ExecutionEnvironmentMismatch(
            f"census commit is absent or malformed: {commit!r}"
        )
    if not mount_proof.startswith(commit + ":"):
        raise ExecutionEnvironmentMismatch(
            "synced checkout mount proof does not name the requested commit"
        )
    output_coordinate = PurePosixPath(output.as_posix())
    durable = PurePosixPath("/root/.cache/sugar/measurements")
    if not output_coordinate.is_absolute() or durable not in output_coordinate.parents:
        raise ExecutionEnvironmentMismatch(
            f"census output is not under the durable measurement mount: {output}"
        )


def authenticate_and_write_preflight() -> CensusLaunch:
        commit = os.environ.get("SUGAR_CENSUS_COMMIT", "")
        mount_proof = os.environ.get("SUGAR_BX_MOUNT_PROOF", "")
        output = Path(os.environ.get("SUGAR_CENSUS_OUTPUT_ROOT", ""))
        require_launch_coordinates(commit, mount_proof, output)
        output.mkdir(parents=True, exist_ok=True)
        probe = output / ".preflight-write"
        probe.write_text("ok\n", encoding="utf-8")
        probe.unlink()
        corpus = authenticated_pandas_corpus()
        if corpus.file_count != 1421:
            raise ExecutionEnvironmentMismatch(
                f"pandas corpus enrollment is {corpus.file_count}; required 1421"
            )
        repo = _REPO
        package_sources = require_synced_source_packages(repo)
        pin_path = repo / "docs/ledgers/pins/pandas-3.0.3.pin.json"
        expected_pin = load_pin(pin_path)
        observed_pin = pin_corpus(
            corpus.root, distribution="pandas", version=corpus.version
        )
        require_pin(expected_pin, observed_pin)
        receipt = {
            "schema": "sugar-pandas-control-effect-preflight/v1",
            "commit": commit,
            "interpreter": interpreter_identity().version,
            "pandasVersion": corpus.version,
            "corpusFiles": corpus.file_count,
            "corpusManifestCid": corpus.manifest_cid,
            "aggregateHash": observed_pin.aggregate_hash,
            "contentOnlyHash": observed_pin.content_only_hash,
            "pathBoundHash": observed_pin.path_bound_hash,
            "corpusRoot": str(corpus.root),
            "outputRoot": str(output),
            "packageSources": package_sources,
            "status": "ready",
        }
        receipt_path = output / "preflight.json"
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        print(receipt_path)
        return CensusLaunch(commit, repo, corpus.root, pin_path, output)


def census_command(launch: CensusLaunch) -> list[str]:
    script = launch.repo / (
        "implementations/python/sugar-lift-py-tests/scripts/"
        "control_effect_recensus.py"
    )
    return [
        sys.executable,
        str(script),
        str(launch.corpus_root),
        "--corpus-root", str(launch.corpus_root),
        "--corpus-distribution", "pandas",
        "--corpus-version", "3.0.3",
        "--require-corpus-pin", str(launch.pin),
        "--repo", str(launch.repo),
        "--commit", launch.commit,
        "--out-dir", str(launch.output),
        "--json", str(launch.output / "recensus.json"),
        "--checkpoint-jsonl", str(launch.output / "checkpoint.jsonl"),
        "--engine-log", str(launch.output / "engine.jsonl"),
        "--progress", str(launch.output / "progress.log"),
    ]


def run_census_under_lease(
    launch: CensusLaunch,
    *,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> int:
    lease = launch.repo / "tools/heavy_measurement_lease.py"
    receipt = launch.output / "lease-record.json"
    status = launch.output / "measurement-status.txt"
    command = [
        sys.executable,
        str(lease),
        "--class", "pandas-control-effect",
        "--record", str(receipt),
        "--status-file", str(status),
        "--",
        *census_command(launch),
    ]
    # The durable coordinate is reused when a killed attempt resumes from its
    # authenticated checkpoint.  Terminal artifacts are not resumable state:
    # leaving any of them in place lets a no-output child authenticate a prior
    # attempt.  Remove only terminals; checkpoint.jsonl remains intact.
    try:
        for name in TERMINAL_ARTIFACTS:
            (launch.output / name).unlink(missing_ok=True)
    except OSError as error:
        print(
            f"CENSUS RESULT REFUSED: cannot reset terminal artifacts: {error}",
            file=sys.stderr,
        )
        return EX_IOERR
    child_env = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(str(path) for path in _SOURCE_ROOTS),
    }
    completed = runner(
        command,
        check=False,
        text=True,
        capture_output=True,
        env=child_env,
    )
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    result = launch.output / "recensus.json"
    if not result.is_file():
        print(
            "CENSUS RESULT REFUSED: lease/census returned without recensus.json",
            file=sys.stderr,
        )
        return EX_IOERR
    try:
        payload = json.loads(result.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"CENSUS RESULT REFUSED: malformed recensus.json: {error}", file=sys.stderr)
        return EX_IOERR
    if "done files=" not in (completed.stdout or ""):
        print("CENSUS RESULT REFUSED: completion summary is absent", file=sys.stderr)
        return EX_IOERR
    if payload.get("commit") != launch.commit or payload.get("sourceStamp", {}).get(
        "commit"
    ) != launch.commit:
        print(
            "CENSUS RESULT REFUSED: result commit/sourceStamp does not match launch",
            file=sys.stderr,
        )
        return EX_IOERR
    denominator = payload.get("denominator", {})
    denominator_exact = (
        denominator.get("complete") is True
        and denominator.get("enrolled") == 1421
        and denominator.get("terminalRows") == 1421
        and denominator.get("completed") == 1421
        and denominator.get("missingFiles") == []
        and denominator.get("duplicateFiles") == []
        and denominator.get("malformedRows") == []
    )
    if not denominator_exact:
        print(
            "CENSUS RESULT REFUSED: denominator is not exact 1421-row conservation",
            file=sys.stderr,
        )
        return EX_IOERR
    return int(completed.returncode)


def execute(
    *,
    authenticate: Callable[[], CensusLaunch] = authenticate_and_write_preflight,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> int:
    try:
        launch = authenticate()
    except Exception as error:
        print(f"CENSUS PREFLIGHT REFUSED: {error}", file=sys.stderr)
        return EX_CONFIG
    return run_census_under_lease(launch, runner=runner)


def main() -> int:
    return execute()


if __name__ == "__main__":
    raise SystemExit(main())
