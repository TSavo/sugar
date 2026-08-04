#!/usr/bin/env python3
"""Execute the enrolled showcase shard with explicit retirement testimony."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

RETIREMENT_SCHEMA_VERSION = 1
SHOWCASE_SCOPE_SCHEMA_VERSION = 2
SHOWCASE_BODY_SCHEMA_VERSION = 2
RETIREMENT_REASON = "out of scope per scope ruling - Java"
SUBJECT_WITNESS_ENV = "SHOWCASE_SUBJECT_WITNESS"
SUBJECT_ID_ENV = "SHOWCASE_SUBJECT_ID"
# The showcase process owns this raw structured witness. The scope consumer
# validates it and never reconstructs terminal identity from prose or A2 counts.
TERMINAL_WITNESS_ENV = "SHOWCASE_TERMINAL_WITNESS"
TERMINAL_IDENTITY_SCHEMA_VERSION = 1
_TERMINAL_IDENTITY_REQUIRED_FIELDS = ("kind", "owner")
_TERMINAL_IDENTITY_OPTIONAL_FIELDS = (
    "coordinate",
    "observed",
    "requested",
    "entrance",
)
_TERMINAL_IDENTITY_FIELDS = frozenset(
    ("schemaVersion",)
    + _TERMINAL_IDENTITY_REQUIRED_FIELDS
    + _TERMINAL_IDENTITY_OPTIONAL_FIELDS
)


class ScopeRefusal(ValueError):
    """The retirement authority or its conservation receipt is malformed."""


def makefile_showcase_roster(path: Path) -> list[str]:
    """Read the ordered SHOWCASE_RUNS assignment without executing Make."""

    lines = path.read_text(encoding="utf-8").splitlines()
    try:
        start = next(i for i, line in enumerate(lines) if line == "SHOWCASE_RUNS = \\")
    except StopIteration as exc:
        raise ScopeRefusal("SHOWCASE_RUNS roster is absent") from exc
    roster: list[str] = []
    for line in lines[start + 1 :]:
        stripped = line.strip()
        if not stripped:
            break
        if stripped.endswith("\\"):
            stripped = stripped[:-1].rstrip()
        if not stripped:
            raise ScopeRefusal("SHOWCASE_RUNS contains an empty enrolled path")
        roster.append(stripped)
    if not roster:
        raise ScopeRefusal("SHOWCASE_RUNS roster is empty")
    if len(roster) != len(set(roster)):
        raise ScopeRefusal("SHOWCASE_RUNS contains a duplicate enrolled path")
    return roster


def load_manifest(path: Path, enrolled: Sequence[str]) -> dict[str, dict[str, str]]:
    """Validate the sole retirement authority against the enrolled roster."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ScopeRefusal(f"retirement manifest unreadable: {path}: {exc}") from exc
    if payload.get("schemaVersion") != RETIREMENT_SCHEMA_VERSION:
        raise ScopeRefusal("retirement manifest schemaVersion must be 1")
    rows = payload.get("retirements")
    if not isinstance(rows, list):
        raise ScopeRefusal("retirement manifest retirements must be a list")
    enrolled_set = set(enrolled)
    result: dict[str, dict[str, str]] = {}
    for ordinal, raw in enumerate(rows):
        if not isinstance(raw, dict):
            raise ScopeRefusal(f"retirement row {ordinal} must be an object")
        row_path = raw.get("path")
        if not isinstance(row_path, str) or not row_path:
            raise ScopeRefusal(f"retirement row {ordinal} has missing path")
        if row_path in result:
            raise ScopeRefusal(f"duplicate retirement: {row_path}")
        if row_path not in enrolled_set:
            raise ScopeRefusal(f"retirement path is not enrolled: {row_path}")
        if raw.get("language") != "java":
            raise ScopeRefusal(f"non-Java retirement: {row_path}")
        if raw.get("outcome") != "retired":
            raise ScopeRefusal(f"unsupported retirement outcome: {row_path}")
        if raw.get("reason") != RETIREMENT_REASON:
            raise ScopeRefusal(f"missing retirement reason: {row_path}")
        assertion = raw.get("assertion")
        if not isinstance(assertion, str) or not assertion.strip():
            raise ScopeRefusal(f"missing retired assertion: {row_path}")
        result[row_path] = {
            "path": row_path,
            "language": "java",
            "outcome": "retired",
            "reason": RETIREMENT_REASON,
            "assertion": assertion,
        }
    return result


def partition(
    enrolled: Sequence[str],
    retirements: Mapping[str, dict[str, str]],
    *,
    shard_count: int,
    shard_index: int,
) -> dict[str, Any]:
    """Partition one shard while retaining the full-roster ordinal."""

    if shard_count < 1 or shard_index < 0 or shard_index >= shard_count:
        raise ScopeRefusal(f"invalid showcase shard {shard_index}/{shard_count}")
    selected = [
        path
        for ordinal, path in enumerate(enrolled)
        if ordinal % shard_count == shard_index
    ]
    retired = [retirements[path] for path in selected if path in retirements]
    scheduled = [path for path in selected if path not in retirements]
    counts = {
        "enrolled": len(selected),
        "executed": len(scheduled),
        "retired": len(retired),
    }
    if counts["executed"] + counts["retired"] != counts["enrolled"]:
        raise ScopeRefusal("showcase scope conservation failed during partition")
    return {
        "schemaVersion": SHOWCASE_SCOPE_SCHEMA_VERSION,
        "measurementClass": "showcase-scope",
        "shardIndex": shard_index,
        "shardCount": shard_count,
        "selected": selected,
        "scheduled": scheduled,
        "retired": retired,
        "counts": counts,
    }


def _safe_log_name(path: str) -> str:
    return path.replace("/", "_").replace(" ", "_") + ".log"


def _write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def validate_terminal_identity(
    raw: object,
    *,
    path: str,
) -> dict[str, object]:
    """Validate and canonically order one producer-owned raw terminal identity."""

    if not isinstance(raw, dict):
        raise ScopeRefusal(f"terminal identity must be an object: {path}")
    unknown = sorted(set(raw) - _TERMINAL_IDENTITY_FIELDS)
    if unknown:
        raise ScopeRefusal(
            f"terminal identity has unsupported fields for {path}: {unknown}"
        )
    if raw.get("schemaVersion") != TERMINAL_IDENTITY_SCHEMA_VERSION:
        raise ScopeRefusal(f"terminal identity schemaVersion must be 1: {path}")
    for name in _TERMINAL_IDENTITY_REQUIRED_FIELDS:
        value = raw.get(name)
        if not isinstance(value, str) or not value.strip():
            raise ScopeRefusal(f"terminal identity lacks nonempty {name}: {path}")
    for name in _TERMINAL_IDENTITY_OPTIONAL_FIELDS:
        if name not in raw:
            continue
        value = raw[name]
        if not isinstance(value, str) or not value.strip():
            raise ScopeRefusal(f"terminal identity has empty optional {name}: {path}")
    canonical: dict[str, object] = {
        "schemaVersion": TERMINAL_IDENTITY_SCHEMA_VERSION,
        "kind": raw["kind"],
        "owner": raw["owner"],
    }
    for name in _TERMINAL_IDENTITY_OPTIONAL_FIELDS:
        if name in raw:
            canonical[name] = raw[name]
    return canonical


def _load_terminal_witness(
    witness_path: Path,
    *,
    showcase_path: str,
) -> tuple[dict[str, object] | None, str | None]:
    try:
        payload = json.loads(witness_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, "terminal-witness-absent"
    except (OSError, ValueError):
        return None, "terminal-witness-malformed"
    try:
        return validate_terminal_identity(payload, path=showcase_path), None
    except ScopeRefusal:
        return None, "terminal-witness-malformed"


def _validate_outcomes(outcomes: object, counts: object) -> None:
    if not isinstance(outcomes, list) or not isinstance(counts, dict):
        raise ScopeRefusal("showcase conservation requires outcomes and counts")
    paths: set[str] = set()
    derived = {
        "enrolled": len(outcomes),
        "executed": 0,
        "retired": 0,
        "passed": 0,
        "failed": 0,
        "unmeasured": 0,
    }
    for ordinal, raw in enumerate(outcomes):
        if not isinstance(raw, dict):
            raise ScopeRefusal(f"showcase outcome {ordinal} must be an object")
        path = raw.get("path")
        if not isinstance(path, str) or not path:
            raise ScopeRefusal(f"showcase outcome {ordinal} has missing path")
        if path in paths:
            raise ScopeRefusal(f"showcase outcome duplicates path: {path}")
        paths.add(path)
        outcome = raw.get("outcome")
        if outcome == "retired":
            if raw.get("language") != "java" or raw.get("reason") != RETIREMENT_REASON:
                raise ScopeRefusal(
                    f"retired outcome lacks Java scope authority: {path}"
                )
            assertion = raw.get("assertion")
            if not isinstance(assertion, str) or not assertion.strip():
                raise ScopeRefusal(f"retired outcome lacks assertion: {path}")
            derived["retired"] += 1
        elif outcome in ("passed", "failed", "unmeasured"):
            exit_code = raw.get("exitCode")
            if not isinstance(exit_code, int):
                raise ScopeRefusal(f"executed outcome lacks integer exitCode: {path}")
            if outcome == "passed" and exit_code != 0:
                raise ScopeRefusal(f"passed showcase has nonzero exitCode: {path}")
            if outcome == "passed":
                witness = raw.get("subjectWitness")
                if witness != {"schemaVersion": 1, "subjectId": path}:
                    raise ScopeRefusal(
                        f"passed showcase lacks authenticated subject witness: {path}"
                    )
                if "terminalIdentity" in raw:
                    raise ScopeRefusal(
                        f"passed showcase claims a terminal identity: {path}"
                    )
            if outcome == "failed" and exit_code == 0:
                raise ScopeRefusal(f"failed showcase has zero exitCode: {path}")
            if outcome == "failed":
                if "terminalIdentity" not in raw:
                    raise ScopeRefusal(
                        f"failed showcase lacks authenticated terminal identity: {path}"
                    )
                validate_terminal_identity(raw["terminalIdentity"], path=path)
            if outcome == "unmeasured":
                reason = raw.get("reason")
                if not isinstance(reason, str) or not reason:
                    raise ScopeRefusal(
                        f"unmeasured showcase lacks named reason: {path}"
                    )
                if "terminalIdentity" in raw:
                    raise ScopeRefusal(
                        f"unmeasured showcase claims a terminal identity: {path}"
                    )
            derived["executed"] += 1
            derived[outcome] += 1
        else:
            raise ScopeRefusal(f"unsupported showcase outcome {outcome!r}: {path}")
    if derived["retired"] + derived["executed"] != derived["enrolled"]:
        raise ScopeRefusal("showcase scope conservation failed")
    for name, value in derived.items():
        if counts.get(name) != value:
            raise ScopeRefusal(
                f"showcase scope conservation mismatch for {name}: "
                f"claimed={counts.get(name)!r} observed={value}"
            )


def validate_shard_body(body: Mapping[str, object]) -> None:
    """Require a conserved per-showcase outcome ledger in the CI body."""

    if body.get("schemaVersion") != SHOWCASE_BODY_SCHEMA_VERSION:
        raise ScopeRefusal("showcase body schemaVersion must be 2")
    if body.get("measurementClass") != "test-showcases":
        raise ScopeRefusal("showcase body has wrong measurementClass")
    outcomes = body.get("showcaseOutcomes")
    counts = body.get("showcaseCounts")
    _validate_outcomes(outcomes, counts)
    assert isinstance(counts, dict)
    failed = counts.get("failed")
    unmeasured = counts.get("unmeasured")
    exit_code = body.get("exitCode")
    if (failed or unmeasured) and exit_code in (0, "0"):
        raise ScopeRefusal(
            "active showcase failure or unmeasured outcome was hidden by exitCode=0"
        )
    if failed == 0 and unmeasured == 0 and exit_code not in (0, "0"):
        raise ScopeRefusal("green executed showcase ledger has nonzero exitCode")


def _collect_join_run(
    bodies: Sequence[Mapping[str, object]],
    *,
    label: str,
) -> tuple[str, dict[str, Mapping[str, object]]]:
    if not bodies:
        raise ScopeRefusal(f"terminal join {label} run has no shard bodies")
    commits: set[str] = set()
    shard_counts: set[int] = set()
    shard_indices: set[int] = set()
    outcomes_by_path: dict[str, Mapping[str, object]] = {}
    for body in bodies:
        validate_shard_body(body)
        commit = body.get("measuredCommit")
        if not isinstance(commit, str) or not commit:
            raise ScopeRefusal(f"terminal join {label} body lacks measuredCommit")
        commits.add(commit)
        shard_count = body.get("shardCount")
        shard_index = body.get("shardIndex")
        if not isinstance(shard_count, int) or not isinstance(shard_index, int):
            raise ScopeRefusal(
                f"terminal join {label} body lacks integer shard identity"
            )
        shard_counts.add(shard_count)
        if shard_index in shard_indices:
            raise ScopeRefusal(
                f"terminal join {label} duplicates shard index {shard_index}"
            )
        shard_indices.add(shard_index)
        outcomes = body.get("showcaseOutcomes")
        assert isinstance(outcomes, list)
        for row in outcomes:
            assert isinstance(row, dict)
            path = row["path"]
            assert isinstance(path, str)
            if path in outcomes_by_path:
                raise ScopeRefusal(
                    f"terminal join {label} duplicates showcase path: {path}"
                )
            outcomes_by_path[path] = row
    if len(commits) != 1:
        raise ScopeRefusal(
            f"terminal join {label} shard bodies disagree on measuredCommit"
        )
    if len(shard_counts) != 1:
        raise ScopeRefusal(f"terminal join {label} shard bodies disagree on shardCount")
    shard_count = next(iter(shard_counts))
    expected = set(range(shard_count))
    if shard_indices != expected:
        raise ScopeRefusal(
            f"terminal join {label} shard attendance mismatch: "
            f"missing={sorted(expected - shard_indices)} "
            f"extra={sorted(shard_indices - expected)}"
        )
    return next(iter(commits)), outcomes_by_path


def join_terminal_bodies(
    before_bodies: Sequence[Mapping[str, object]],
    after_bodies: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Join one run's failed rows to the next run by exact showcase path."""

    before_commit, before_rows = _collect_join_run(before_bodies, label="before")
    after_commit, after_rows = _collect_join_run(after_bodies, label="after")
    rows: list[dict[str, object]] = []
    for path in sorted(before_rows):
        before = before_rows[path]
        if before.get("outcome") != "failed":
            continue
        before_terminal = validate_terminal_identity(
            before.get("terminalIdentity"), path=path
        )
        after = after_rows.get(path)
        if after is None:
            raise ScopeRefusal(f"terminal join after run is missing row: {path}")
        after_outcome = after.get("outcome")
        if after_outcome == "passed":
            rows.append(
                {
                    "path": path,
                    "transition": "cleared",
                    "beforeTerminalIdentity": before_terminal,
                }
            )
            continue
        if after_outcome == "unmeasured":
            raise ScopeRefusal(f"terminal join cannot classify unmeasured row: {path}")
        if after_outcome != "failed":
            raise ScopeRefusal(
                f"terminal join cannot classify after outcome "
                f"{after_outcome!r}: {path}"
            )
        after_terminal = validate_terminal_identity(
            after.get("terminalIdentity"), path=path
        )
        transition = (
            "still-failing-same-terminal"
            if before_terminal == after_terminal
            else "moved-to-named-terminal"
        )
        rows.append(
            {
                "path": path,
                "transition": transition,
                "beforeTerminalIdentity": before_terminal,
                "afterTerminalIdentity": after_terminal,
            }
        )
    counts = {
        "inputFailures": len(rows),
        "cleared": sum(row["transition"] == "cleared" for row in rows),
        "stillFailingSameTerminal": sum(
            row["transition"] == "still-failing-same-terminal" for row in rows
        ),
        "movedToNamedTerminal": sum(
            row["transition"] == "moved-to-named-terminal" for row in rows
        ),
    }
    classified = (
        counts["cleared"]
        + counts["stillFailingSameTerminal"]
        + counts["movedToNamedTerminal"]
    )
    if classified != counts["inputFailures"]:
        raise ScopeRefusal("terminal join conservation failed")
    return {
        "schemaVersion": 1,
        "measurementClass": "showcase-terminal-transition",
        "status": "completed",
        "beforeMeasuredCommit": before_commit,
        "afterMeasuredCommit": after_commit,
        "counts": counts,
        "rows": rows,
    }


def seal_shard_body(
    scope_receipt: Mapping[str, object],
    *,
    measured_commit: str,
    exit_code: int,
    output_path: Path,
) -> dict[str, object]:
    """Seal the conserved scope ledger into the CI attendance body."""

    if scope_receipt.get("measurementClass") != "showcase-scope":
        raise ScopeRefusal("scope receipt has wrong measurementClass")
    if scope_receipt.get("schemaVersion") != SHOWCASE_SCOPE_SCHEMA_VERSION:
        raise ScopeRefusal("scope receipt schemaVersion must be 2")
    shard_index = scope_receipt.get("shardIndex")
    shard_count = scope_receipt.get("shardCount")
    if not isinstance(shard_index, int) or not isinstance(shard_count, int):
        raise ScopeRefusal("scope receipt lacks integer shard identity")
    outcomes = scope_receipt.get("outcomes")
    counts = scope_receipt.get("counts")
    _validate_outcomes(outcomes, counts)
    body: dict[str, object] = {
        "schemaVersion": SHOWCASE_BODY_SCHEMA_VERSION,
        "measurementClass": "test-showcases",
        "shardIndex": shard_index,
        "shardCount": shard_count,
        "measuredCommit": measured_commit,
        "status": "unmeasured" if counts.get("unmeasured") else "completed",
        "exitCode": exit_code,
        "showcaseCounts": counts,
        "showcaseOutcomes": outcomes,
    }
    validate_shard_body(body)
    _write_json_atomic(output_path, body)
    return body


def run_shard(
    *,
    repo_root: Path,
    manifest_path: Path,
    enrolled: Sequence[str],
    shard_count: int,
    shard_index: int,
    attr_dir: Path,
    receipt_path: Path,
    failed_path: Path | None = None,
    summary_path: Path | None = None,
) -> int:
    """Execute active rows, testify retired rows, and write one conserved receipt."""

    repo_root = repo_root.resolve()
    retirements = load_manifest(manifest_path, enrolled)
    plan = partition(
        enrolled, retirements, shard_count=shard_count, shard_index=shard_index
    )
    attr_dir.mkdir(parents=True, exist_ok=True)
    failed_path = failed_path or attr_dir / f"shard-{shard_index}-failed.txt"
    summary_path = summary_path or attr_dir / f"shard-{shard_index}-summary.log"
    outcomes: list[dict[str, object]] = []
    failed: list[str] = []
    unmeasured: list[str] = []
    failed_logs: list[tuple[str, str]] = []

    for path in plan["selected"]:
        retirement = retirements.get(path)
        print()
        print(f"==== [showcase shard {shard_index}/{shard_count}] {path} ====")
        if retirement is not None:
            print(
                "outcome=RETIRED "
                f"path={path} language=java reason={RETIREMENT_REASON}"
            )
            outcomes.append(dict(retirement))
            continue

        log_path = attr_dir / _safe_log_name(path)
        witness_path = attr_dir / (_safe_log_name(path) + ".subject-witness")
        terminal_witness_path = attr_dir / (
            _safe_log_name(path) + ".terminal-witness.json"
        )
        for stale_witness_path in (witness_path, terminal_witness_path):
            try:
                stale_witness_path.unlink()
            except FileNotFoundError:
                pass
        subject_id = path
        process_env = os.environ.copy()
        process_env[SUBJECT_WITNESS_ENV] = str(witness_path.resolve())
        process_env[SUBJECT_ID_ENV] = subject_id
        process_env[TERMINAL_WITNESS_ENV] = str(terminal_witness_path.resolve())
        try:
            proc = subprocess.run(
                [str(repo_root / path)],
                cwd=repo_root,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                errors="replace",
                check=False,
                env=process_env,
            )
            output = proc.stdout
            returncode = proc.returncode
        except OSError as exc:
            output = f"showcase execution failed before body: {exc}\n"
            returncode = 127
        log_path.write_text(output, encoding="utf-8")
        sys.stdout.write(output)
        if output and not output.endswith("\n"):
            print()
        if returncode == 0:
            if terminal_witness_path.exists():
                reason = "terminal-witness-on-pass"
                marker = f"==== {path}: UNMEASURED {reason} ====\n"
                sys.stdout.write(marker)
                with log_path.open("a", encoding="utf-8") as handle:
                    handle.write(marker)
                outcomes.append(
                    {
                        "path": path,
                        "outcome": "unmeasured",
                        "exitCode": 0,
                        "reason": reason,
                    }
                )
                unmeasured.append(path)
                continue
            try:
                witnessed_subject = witness_path.read_text(encoding="utf-8") == (
                    subject_id + "\n"
                )
            except OSError:
                witnessed_subject = False
            if witnessed_subject:
                outcomes.append(
                    {
                        "path": path,
                        "outcome": "passed",
                        "exitCode": 0,
                        "subjectWitness": {
                            "schemaVersion": 1,
                            "subjectId": subject_id,
                        },
                    }
                )
            else:
                reason = "subject-witness-absent"
                marker = f"==== {path}: UNMEASURED {reason} ====\n"
                sys.stdout.write(marker)
                with log_path.open("a", encoding="utf-8") as handle:
                    handle.write(marker)
                outcomes.append(
                    {
                        "path": path,
                        "outcome": "unmeasured",
                        "exitCode": 0,
                        "reason": reason,
                    }
                )
                unmeasured.append(path)
        else:
            terminal_identity, terminal_failure = _load_terminal_witness(
                terminal_witness_path,
                showcase_path=path,
            )
            if terminal_failure is not None:
                marker = f"==== {path}: UNMEASURED {terminal_failure} ====\n"
                sys.stdout.write(marker)
                with log_path.open("a", encoding="utf-8") as handle:
                    handle.write(marker)
                outcomes.append(
                    {
                        "path": path,
                        "outcome": "unmeasured",
                        "exitCode": returncode,
                        "reason": terminal_failure,
                    }
                )
                unmeasured.append(path)
            else:
                assert terminal_identity is not None
                marker = f"==== {path}: FAIL ====\n"
                sys.stdout.write(marker)
                with log_path.open("a", encoding="utf-8") as handle:
                    handle.write(marker)
                outcomes.append(
                    {
                        "path": path,
                        "outcome": "failed",
                        "exitCode": returncode,
                        "terminalIdentity": terminal_identity,
                    }
                )
                failed.append(path)
                failed_logs.append((path, log_path.read_text(encoding="utf-8")))

    counts = {
        "enrolled": len(outcomes),
        "executed": sum(row["outcome"] != "retired" for row in outcomes),
        "retired": sum(row["outcome"] == "retired" for row in outcomes),
        "passed": sum(row["outcome"] == "passed" for row in outcomes),
        "failed": sum(row["outcome"] == "failed" for row in outcomes),
        "unmeasured": sum(row["outcome"] == "unmeasured" for row in outcomes),
    }
    _validate_outcomes(outcomes, counts)
    if counts["enrolled"] != plan["counts"]["enrolled"]:
        raise ScopeRefusal("showcase scope conservation lost an enrolled row")
    receipt = {
        "schemaVersion": SHOWCASE_SCOPE_SCHEMA_VERSION,
        "measurementClass": "showcase-scope",
        "shardIndex": shard_index,
        "shardCount": shard_count,
        "counts": counts,
        "outcomes": outcomes,
    }
    _write_json_atomic(receipt_path, receipt)
    failed_path.write_text("".join(f"{path}\n" for path in failed), encoding="utf-8")
    summary = "".join(
        f"==== [showcase shard {shard_index}/{shard_count}] {path} ====\n{log}"
        for path, log in failed_logs
    )
    if failed:
        summary += f"==== test-showcases FAIL: {' '.join(failed)} ====\n"
    if unmeasured:
        summary += f"==== test-showcases UNMEASURED: {' '.join(unmeasured)} ====\n"
    summary_path.write_text(summary, encoding="utf-8")
    print()
    print(
        f"==== showcase shard {shard_index}/{shard_count} "
        f"enrolled={counts['enrolled']} executed={counts['executed']} "
        f"retired={counts['retired']} ===="
    )
    return 1 if failed or unmeasured else 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run", help="execute one conserved showcase shard")
    run.add_argument("--repo-root", type=Path, required=True)
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--shard-count", type=int, required=True)
    run.add_argument("--shard-index", type=int, required=True)
    run.add_argument("--attr-dir", type=Path, required=True)
    run.add_argument("--receipt", type=Path, required=True)
    run.add_argument("--failed-path", type=Path, required=True)
    run.add_argument("--summary-path", type=Path, required=True)
    run.add_argument("enrolled", nargs="+")
    seal = subparsers.add_parser(
        "seal-body", help="seal one scope receipt into a CI attendance body"
    )
    seal.add_argument("--scope-receipt", type=Path, required=True)
    seal.add_argument("--output", type=Path, required=True)
    seal.add_argument("--measured-commit", required=True)
    seal.add_argument("--exit-code", type=int, required=True)
    join = subparsers.add_parser(
        "join-terminals",
        help="join before/after failed rows by sealed raw terminal identity",
    )
    join.add_argument("--before", type=Path, nargs="+", required=True)
    join.add_argument("--after", type=Path, nargs="+", required=True)
    join.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "run":
        try:
            return run_shard(
                repo_root=args.repo_root,
                manifest_path=args.manifest,
                enrolled=args.enrolled,
                shard_count=args.shard_count,
                shard_index=args.shard_index,
                attr_dir=args.attr_dir,
                receipt_path=args.receipt,
                failed_path=args.failed_path,
                summary_path=args.summary_path,
            )
        except ScopeRefusal as exc:
            print(f"showcase-scope: REFUSED: {exc}", file=sys.stderr)
            return 2
    if args.command == "seal-body":
        try:
            scope_receipt = json.loads(args.scope_receipt.read_text(encoding="utf-8"))
            seal_shard_body(
                scope_receipt,
                measured_commit=args.measured_commit,
                exit_code=args.exit_code,
                output_path=args.output,
            )
            return 0
        except (OSError, ValueError, ScopeRefusal) as exc:
            print(f"showcase-scope: REFUSED: {exc}", file=sys.stderr)
            return 2
    if args.command == "join-terminals":
        try:
            before = [
                json.loads(path.read_text(encoding="utf-8")) for path in args.before
            ]
            after = [
                json.loads(path.read_text(encoding="utf-8")) for path in args.after
            ]
            joined = join_terminal_bodies(before, after)
            _write_json_atomic(args.output, joined)
            return 0
        except (OSError, ValueError, ScopeRefusal) as exc:
            print(f"showcase-scope: REFUSED: {exc}", file=sys.stderr)
            return 2
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
