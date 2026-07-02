from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "sugar_lift_py_tests"


# Factory stays last: literal_call_report.py is the largest swamp and is the
# deliberately-last drain target from #3055.
PACKAGE_TARGETS: dict[str, Path] = {
    "outcome": SRC / "outcome",
    "claim": SRC / "claim",
    "floor": SRC / "floor",
    "effect": SRC / "effect",
    "context": SRC / "context",
    "sugar_body": SRC / "sugar_body",
    "constraint_flow": SRC / "constraint_flow",
    "temporal": SRC / "temporal",
    "audit_only": SRC / "audit_only",
    "operations": SRC / "operations",
    "sugar": SRC / "sugar",
    "idd": SRC / "idd",
    "lift": SRC / "lift",
    "kit_rpc": SRC / "kit_rpc",
    "factory": SRC / "factory",
}


EXPECTED_PYRIGHT_ERRORS: dict[str, int] = {
    "outcome": 0,
    "claim": 0,
    "floor": 0,
    "effect": 0,
    "context": 0,
    "sugar_body": 0,
    "constraint_flow": 0,
    "temporal": 0,
    "audit_only": 0,
    "operations": 0,
    "sugar": 0,
    "idd": 0,
    "lift": 0,
    "kit_rpc": 0,
    "factory": 0,
}


@dataclass(frozen=True)
class PyrightPackageResult:
    package: str
    errors: int
    files_analyzed: int
    diagnostics: tuple[str, ...]


def test_pyright_error_counts_match_ratchet() -> None:
    observed = {
        package: result
        for package in PACKAGE_TARGETS
        if (result := _run_pyright_package(package))
    }
    failures = _ratchet_failures(
        {package: result.errors for package, result in observed.items()},
        EXPECTED_PYRIGHT_ERRORS,
    )

    assert not failures, _render_report(observed, failures)


def test_ratchet_rejects_new_errors_in_clean_package() -> None:
    failures = _ratchet_failures(
        {"outcome": 1},
        {"outcome": 0},
    )

    assert failures == [
        "outcome: observed 1 pyright error(s), expected at most 0; "
        "new type error introduced"
    ]


def test_ratchet_rejects_stale_pin() -> None:
    failures = _ratchet_failures(
        {"operations": 38},
        {"operations": 39},
    )

    assert failures == [
        "operations: observed 38 pyright error(s), expected 39; "
        "stale pin, lower EXPECTED_PYRIGHT_ERRORS"
    ]


def test_pinned_debt_at_exact_count_stays_green() -> None:
    assert _ratchet_failures({"factory": 62}, {"factory": 62}) == []


def _run_pyright_package(package: str) -> PyrightPackageResult:
    target = PACKAGE_TARGETS[package]
    env = dict(os.environ)
    env["PYTHONPATH"] = _with_src_on_pythonpath(env.get("PYTHONPATH", ""))
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pyright",
            "--project",
            str(ROOT / "pyrightconfig.json"),
            "--outputjson",
            str(target),
        ],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode not in {0, 1}:
        raise AssertionError(
            f"pyright failed for {package} with exit {proc.returncode}\n"
            f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"pyright did not emit JSON for {package}\n"
            f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        ) from exc
    diagnostics = tuple(
        f"{Path(item['file']).relative_to(ROOT)}:{item['range']['start']['line'] + 1}: "
        f"{item['message']}"
        for item in payload.get("generalDiagnostics", ())
    )
    summary = payload["summary"]
    return PyrightPackageResult(
        package=package,
        errors=int(summary["errorCount"]),
        files_analyzed=int(summary["filesAnalyzed"]),
        diagnostics=diagnostics,
    )


def _ratchet_failures(observed: dict[str, int], expected: dict[str, int]) -> list[str]:
    failures: list[str] = []
    for package, expected_count in expected.items():
        actual = observed[package]
        if actual > expected_count:
            failures.append(
                f"{package}: observed {actual} pyright error(s), expected at most "
                f"{expected_count}; new type error introduced"
            )
        elif actual < expected_count:
            failures.append(
                f"{package}: observed {actual} pyright error(s), expected "
                f"{expected_count}; stale pin, lower EXPECTED_PYRIGHT_ERRORS"
            )
    return failures


def _render_report(
    observed: dict[str, PyrightPackageResult],
    failures: list[str],
) -> str:
    lines = ["pyright ratchet failures:", *failures, "", "R(pyright-errors):"]
    for package, result in observed.items():
        lines.append(
            f"  {package}: {result.errors} "
            f"(files={result.files_analyzed}, pin={EXPECTED_PYRIGHT_ERRORS[package]})"
        )
        if result.errors:
            for diagnostic in result.diagnostics[:5]:
                lines.append(f"    - {diagnostic}")
            if len(result.diagnostics) > 5:
                lines.append(f"    - ... {len(result.diagnostics) - 5} more")
    return "\n".join(lines)


def _with_src_on_pythonpath(existing: str) -> str:
    parts = [str(ROOT / "src")]
    if existing:
        parts.append(existing)
    return os.pathsep.join(parts)
