#!/usr/bin/env python3
"""Authenticate managed task preconditions before subject execution."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

REFUSAL = 70


def _load_json_text(raw: str, label: str) -> object:
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} is not valid JSON: {exc}") from exc


def falsify(plan: object, axes: object) -> int:
    if not isinstance(plan, dict) or not isinstance(plan.get("checks"), list):
        raise ValueError("precondition plan lacks checks")
    if not isinstance(axes, dict) or axes.get("schemaVersion") != 1:
        raise ValueError("precondition axes schemaVersion must be 1")
    rows = axes.get("axes")
    if not isinstance(rows, list):
        raise ValueError("precondition axes must be a list")
    checks = plan["checks"]
    uncovered = []
    for ordinal, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"precondition axis {ordinal} is not an object")
        axis = row.get("axis")
        kind = row.get("expectedKind")
        source = row.get("expectedSourcePrefix")
        if not all(isinstance(value, str) and value for value in (axis, kind, source)):
            raise ValueError(f"precondition axis {ordinal} is malformed")
        if not any(
            isinstance(check, dict)
            and check.get("kind") == kind
            and isinstance(check.get("source"), str)
            and check["source"].startswith(source)
            for check in checks
        ):
            uncovered.append(row)
            print(
                "sugarbin: crime=unpredicted-precondition-axis "
                f"axis={axis} expectedKind={kind} expectedSourcePrefix={source}",
                file=sys.stderr,
            )
    print(f"R_precondition_axes_discovered={len(rows)}")
    print(f"R_precondition_axes_predicted={len(rows) - len(uncovered)}")
    print(f"R_unpredicted_precondition_axes={len(uncovered)}")
    return REFUSAL if uncovered else 0


def _elapsed_ms(started: int) -> int:
    return max(0, (time.monotonic_ns() - started) // 1_000_000)


def _named_refusal(crime: str, check: dict[str, object], **fields: object) -> int:
    details = " ".join(f"{name}={value}" for name, value in fields.items())
    print(
        f"sugarbin: crime={crime} kind={check['kind']} "
        f"source={check['source']} {details}".rstrip(),
        file=sys.stderr,
    )
    return REFUSAL


def check_declared_prerequisites(plan: object) -> int:
    if not isinstance(plan, dict) or plan.get("schemaVersion") != 1:
        raise ValueError("precondition plan schemaVersion must be 1")
    checks = plan.get("checks")
    if not isinstance(checks, list):
        raise ValueError("precondition plan lacks checks")
    for check in checks:
        if not isinstance(check, dict):
            raise ValueError("precondition check is not an object")
        kind = check.get("kind")
        if kind not in ("command", "toolchain-component"):
            continue
        started = time.monotonic_ns()
        if kind == "command":
            name = check.get("name")
            if not isinstance(name, str) or not name:
                raise ValueError("command precondition lacks name")
            if shutil.which(name) is None:
                return _named_refusal("missing-managed-command", check, name=name)
        else:
            name = check.get("name")
            channel = check.get("channel")
            if not isinstance(name, str) or not isinstance(channel, str):
                raise ValueError("toolchain component precondition is malformed")
            rustup = shutil.which("rustup")
            if rustup is None:
                return _named_refusal(
                    "missing-toolchain-component", check, name=name, channel=channel,
                    reason="rustup-absent",
                )
            result = subprocess.run(
                [rustup, "component", "list", "--toolchain", channel, "--installed"],
                check=False,
                capture_output=True,
                text=True,
            )
            installed = {
                line.split()[0]
                for line in result.stdout.splitlines()
                if line.strip()
            }
            if result.returncode != 0 or not any(
                item == name or item.startswith(f"{name}-") for item in installed
            ):
                return _named_refusal(
                    "missing-toolchain-component", check, name=name, channel=channel,
                    rustupExit=result.returncode,
                )
        print(
            f"sugarbin: precondition={kind} name={check.get('name')} "
            f"source={check.get('source')} elapsed_ms={_elapsed_ms(started)} outcome=pass",
            file=sys.stderr,
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    falsifier = subparsers.add_parser("falsify")
    falsifier.add_argument("--plan-json", required=True)
    falsifier.add_argument("--axes", type=Path, required=True)
    runner = subparsers.add_parser("run")
    runner.add_argument("--plan-json", required=True)
    runner.add_argument("--artifact-root", type=Path, required=True)
    runner.add_argument("subject", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        plan = _load_json_text(args.plan_json, "precondition plan")
        if args.command == "falsify":
            axes = json.loads(args.axes.read_text(encoding="utf-8"))
            return falsify(plan, axes)
        subject = args.subject[1:] if args.subject[:1] == ["--"] else args.subject
        if not subject:
            raise ValueError("precondition runner lacks subject command")
        status = check_declared_prerequisites(plan)
        if status != 0:
            return status
        os.execvp(subject[0], subject)
        raise AssertionError("os.execvp returned")
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        print(f"sugarbin: crime=precondition-instrument-invalid error={exc}", file=sys.stderr)
        return REFUSAL


if __name__ == "__main__":
    raise SystemExit(main())
