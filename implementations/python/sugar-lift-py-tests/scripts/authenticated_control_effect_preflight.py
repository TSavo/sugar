#!/usr/bin/env python3
"""Refuse before the pandas scoreboard unless launch identity is complete."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path, PurePosixPath

from sugar_lift_py_tests.authenticated_pytest import (
    ExecutionEnvironmentMismatch,
    authenticated_pandas_corpus,
    interpreter_identity,
)
from sugar_lift_py_tests.corpus_pin import load_pin, pin_corpus, require_pin


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


def main() -> int:
    try:
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
        repo = Path(__file__).resolve().parents[4]
        expected_pin = load_pin(repo / "docs/ledgers/pins/pandas-3.0.3.pin.json")
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
            "status": "ready",
        }
        receipt_path = output / "preflight.json"
        receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        print(receipt_path)
        return 0
    except Exception as error:
        print(f"CENSUS PREFLIGHT REFUSED: {error}", file=sys.stderr)
        return 78


if __name__ == "__main__":
    raise SystemExit(main())
