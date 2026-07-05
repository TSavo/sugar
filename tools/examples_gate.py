#!/usr/bin/env python3
"""Sequential examples gate with a ratcheted green/named-red fixture."""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import TextIO

LAST_DIFF_TEXT = ""


@dataclass(frozen=True)
class FailurePattern:
    shape: str
    regex: re.Pattern[str]


FAILURE_PATTERNS: tuple[FailurePattern, ...] = (
    FailurePattern(
        "walk-panic/opaque-syn-variant",
        re.compile(r"assignment target collector refused opaque syn::Expr variant"),
    ),
    FailurePattern(
        "build-failed/sugar-walk-bridge-source-symbol",
        re.compile(r"bridge_source_symbol|could not compile `?sugar-walk`?"),
    ),
    FailurePattern(
        "kit-transform/callsite-line-null",
        re.compile(r"callsite\.line must be an integer, got null"),
    ),
    FailurePattern(
        "rust-lift-panic/chained-comparison",
        re.compile(r"comparison operators cannot be chained"),
    ),
    FailurePattern(
        "durable-row-missing/scientific-python-showcase",
        re.compile(
            r"MISSING: durable verify|missing good rot90 discharge|"
            r"missing pandas Series\.sum|missing sklearn LogisticRegression"
        ),
    ),
    FailurePattern(
        "prove-refused/provenance-kind-required",
        re.compile(
            r"lacks required provenance KIND|expected witness discharge, got refused"
        ),
    ),
    FailurePattern(
        "prove-refused/expected-discharge-rows",
        re.compile(
            r"expected all consistency rows discharged|"
            r"expected the witness-package to DISCHARGE"
        ),
    ),
    FailurePattern(
        "mint-missing/forall-vampire-claim-rows",
        re.compile(r"missing forall-vampire claim row"),
    ),
    FailurePattern(
        "mint-missing/base64-decode-property-rows",
        re.compile(r"no base64_decode property rows"),
    ),
    FailurePattern(
        "prove-output/empty-json-receipt",
        re.compile(r"expected JSON receipt, got non-JSON output: <empty output>"),
    ),
    FailurePattern(
        "missing-universe-atom/int32-eq-bv-expr",
        re.compile(
            r"carries no int32\.eq-bv-expr universe atom|"
            r"no int32\.eq-bv-expr universe atom for abs\(MIN_VALUE\)"
        ),
    ),
    FailurePattern(
        "prove-refused/panic-callsite-row",
        re.compile(r"contract verify rc=1 expected 0|panic_callsite"),
    ),
    FailurePattern(
        "prove-output/no-json-report",
        re.compile(r"no JSON report found"),
    ),
    FailurePattern(
        "audit-missing/pandas-package-audit",
        re.compile(r"expected one pandas package audit, got 0"),
    ),
    FailurePattern(
        "kit-selection/rust-component-unclaimed",
        re.compile(
            r"Rust workspace detected at Cargo\.toml, but no Sugar Rust kit component claimed it"
        ),
    ),
    FailurePattern(
        "verdict-drift/expected-proven-label",
        re.compile(r"expected PROVEN"),
    ),
    FailurePattern(
        "prove-red/bodyguard-precondition",
        re.compile(r"good verify expected exit 0 got 1|good: expected exit 0, got 1"),
    ),
    FailurePattern(
        "verdict-drift/refused-row-expectation",
        re.compile(r"expected refused rows"),
    ),
    FailurePattern(
        "plugin-entrypoint/stale-python-lsp-module",
        re.compile(r"No module named sugar_lift_py_tests\.lsp"),
    ),
    FailurePattern(
        "verdict-drift/membership-refutation",
        re.compile(
            r"expected (?:a )?refuted (?:\(unsatisfied\)|/unsatisfied) membership row"
        ),
    ),
    FailurePattern(
        "mint-output/regex-membership-ended-during-mint",
        re.compile(
            r"mint: lift regex-match assertions -> str\.in-regex membership rows"
        ),
    ),
    FailurePattern(
        "claim-rows-missing/std-core-panic-callsite",
        re.compile(r"missing required claimed rows"),
    ),
)


def discover_scripts(root: pathlib.Path, *, suite: str = "smoke") -> list[str]:
    examples = root / "examples"
    if suite == "smoke":
        return sorted(
            path.relative_to(root).as_posix() for path in examples.glob("*/run.sh")
        )
    if suite != "extended":
        raise ValueError(f"unknown examples gate suite {suite!r}")
    prove = examples / "signup-service" / "prove.sh"
    if prove.exists():
        return [prove.relative_to(root).as_posix()]
    return []


def _excerpt(text: str, max_lines: int = 20) -> str:
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines[-max_lines:])


def classify_failure(log_text: str) -> str:
    haystack = "\n".join(log_text.splitlines()[-200:])
    for pattern in FAILURE_PATTERNS:
        if pattern.regex.search(haystack):
            return pattern.shape
    return "unclassified/example-failure"


def run_script(
    *,
    root: pathlib.Path,
    script: str,
    index: int,
    total: int,
    log_dir: pathlib.Path,
    timeout_seconds: int,
    nice: int,
    output: TextIO,
) -> dict[str, object]:
    log_dir.mkdir(parents=True, exist_ok=True)
    safe_name = script.replace("/", "__")
    log_path = log_dir / f"{index:02d}-{safe_name}.log"
    print(f"[{index}/{total}] START {script}", file=output, flush=True)
    command = ["bash", script]
    if nice:
        command = ["nice", "-n", str(nice), *command]
    start = time.monotonic()
    try:
        with log_path.open("wb") as log:
            proc = subprocess.run(
                command,
                cwd=root,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=timeout_seconds,
            )
        rc = proc.returncode
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        rc = 124
        timed_out = True
        with log_path.open("ab") as log:
            log.write(f"\nexamples_gate: timed out after {timeout_seconds}s\n".encode())
            if exc.output:
                log.write(exc.output)
    seconds = time.monotonic() - start
    log_text = log_path.read_text(encoding="utf-8", errors="replace")
    if rc == 0:
        verdict = "GREEN"
        shape = None
        excerpt = ""
    elif timed_out:
        verdict = "NAMED_RED"
        shape = "timeout/per-example"
        excerpt = _excerpt(log_text)
    else:
        verdict = "NAMED_RED"
        shape = classify_failure(log_text)
        excerpt = _excerpt(log_text)
    print(
        f"[{index}/{total}] END rc={rc} seconds={seconds:.1f} shape={shape or 'green'} {script}",
        file=output,
        flush=True,
    )
    return {
        "name": script,
        "rc": rc,
        "seconds": round(seconds, 3),
        "verdict": verdict,
        "failure_shape": shape,
        "failure_excerpt": excerpt,
        "log_path": str(log_path),
    }


def run_all(
    *,
    root: pathlib.Path,
    log_dir: pathlib.Path,
    timeout_seconds: int,
    nice: int,
    suite: str,
    output: TextIO,
) -> dict[str, object]:
    scripts = discover_scripts(root, suite=suite)
    rows = [
        run_script(
            root=root,
            script=script,
            index=index,
            total=len(scripts),
            log_dir=log_dir,
            timeout_seconds=timeout_seconds,
            nice=nice,
            output=output,
        )
        for index, script in enumerate(scripts, start=1)
    ]
    return {
        "version": 1,
        "suite": suite,
        "root": str(root),
        "generated_at_unix": int(time.time()),
        "examples": rows,
    }


def _load_json(path: pathlib.Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _rows_by_name(
    data: dict[str, object], *, source: str
) -> dict[str, dict[str, object]]:
    rows = data.get("examples")
    if not isinstance(rows, list):
        raise ValueError(f"{source} has no examples list")
    out: dict[str, dict[str, object]] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(f"{source} contains a non-object row")
        name = row.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError(f"{source} contains a row without a string name")
        if name in out:
            raise ValueError(f"{source} contains duplicate row {name}")
        out[name] = row
    return out


def _expected_shape(row: dict[str, object]) -> str | None:
    value = row.get("failure_shape")
    return value if isinstance(value, str) else None


def compare_expectations(
    expectations: dict[str, object],
    observed: dict[str, object],
) -> list[str]:
    expected_rows = _rows_by_name(expectations, source="expectations")
    observed_rows = _rows_by_name(observed, source="observed summary")
    diffs: list[str] = []
    expected_suite = expectations.get("suite")
    observed_suite = observed.get("suite")
    if isinstance(expected_suite, str) and isinstance(observed_suite, str):
        if expected_suite != observed_suite:
            diffs.append(
                f"SUITE_MISMATCH expected {expected_suite} observed {observed_suite}"
            )

    for name in sorted(observed_rows.keys() - expected_rows.keys()):
        row = observed_rows[name]
        diffs.append(
            f"UNEXPECTED_EXAMPLE {name} observed {row.get('verdict')} {row.get('failure_shape')}"
        )

    for name in sorted(expected_rows.keys() - observed_rows.keys()):
        diffs.append(
            f"MISSING_EXAMPLE {name} expected {expected_rows[name].get('expected')}"
        )

    for name in sorted(expected_rows.keys() & observed_rows.keys()):
        expected = expected_rows[name]
        actual = observed_rows[name]
        expected_status = expected.get("expected")
        actual_status = actual.get("verdict")
        actual_shape = actual.get("failure_shape")
        expected_shape = _expected_shape(expected)

        if expected_status == "GREEN":
            if actual_status != "GREEN":
                diffs.append(
                    f"NEW_RED {name} expected GREEN observed {actual_shape or actual_status}"
                )
            continue

        if expected_status == "NAMED_RED":
            if expected_shape is None:
                diffs.append(f"BAD_EXPECTATION {name} NAMED_RED requires failure_shape")
                continue
            if actual_status == "GREEN":
                diffs.append(
                    f"PROMOTED_RED {name} expected {expected_shape} observed GREEN"
                )
            elif actual_status != "NAMED_RED":
                diffs.append(
                    f"CHANGED_STATUS {name} expected NAMED_RED observed {actual_status}"
                )
            elif actual_shape != expected_shape:
                diffs.append(
                    f"CHANGED_RED {name} expected {expected_shape} observed {actual_shape}"
                )
            continue

        diffs.append(
            f"BAD_EXPECTATION {name} expected field must be GREEN or NAMED_RED"
        )

    return diffs


def check_expectations(
    *,
    expectation_path: pathlib.Path,
    summary_path: pathlib.Path,
    output: TextIO,
) -> int:
    global LAST_DIFF_TEXT
    expectations = _load_json(expectation_path)
    observed = _load_json(summary_path)
    diffs = compare_expectations(expectations, observed)
    if diffs:
        LAST_DIFF_TEXT = "\n".join(diffs)
        print("examples-gate: FAIL", file=output)
        print(LAST_DIFF_TEXT, file=output)
        return 1
    LAST_DIFF_TEXT = ""
    print("examples-gate: PASS", file=output)
    return 0


def write_summary(path: pathlib.Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=pathlib.Path, default=pathlib.Path.cwd())
    parser.add_argument(
        "--expectations",
        type=pathlib.Path,
        default=pathlib.Path("docs/audits/examples_gate_expectations.json"),
    )
    parser.add_argument(
        "--summary-json",
        type=pathlib.Path,
        default=pathlib.Path(".out/examples-gate-summary.json"),
    )
    parser.add_argument(
        "--log-dir",
        type=pathlib.Path,
        default=pathlib.Path(".out/examples-gate-logs"),
    )
    parser.add_argument("--from-summary", type=pathlib.Path)
    parser.add_argument("--suite", choices=("smoke", "extended"), default="smoke")
    parser.add_argument("--timeout-seconds", type=int, default=3600)
    parser.add_argument("--nice", type=int, default=10)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    root = args.root.resolve()
    summary_path = args.summary_json
    if args.from_summary is None:
        summary = run_all(
            root=root,
            log_dir=args.log_dir,
            timeout_seconds=args.timeout_seconds,
            nice=args.nice,
            suite=args.suite,
            output=sys.stdout,
        )
        write_summary(summary_path, summary)
    else:
        summary_path = args.from_summary
    return check_expectations(
        expectation_path=args.expectations,
        summary_path=summary_path,
        output=sys.stdout,
    )


if __name__ == "__main__":
    raise SystemExit(main())
