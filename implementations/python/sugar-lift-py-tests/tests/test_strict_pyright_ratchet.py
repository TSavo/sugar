"""Strict-mode pyright ratchet over the typed-frontier hierarchy-edge files.

pyrightconfig.json runs the repo in basic mode; that ratchet lives in
test_type_checker_ratchet.py. This is a SEPARATE, narrower lane: it re-runs
pyright in STRICT mode scoped to exactly the files #3657's priority list named
as closeable-but-loose (FloorDispatchSurface/FloorValue, FactoryBuildContext,
FactoryGapEffect, the SugarBody/FactoryBuildResult edge, and the two DTOs that
close their dict[str, Any] fallback lanes). Whole-repo strict is not the ask;
these six-plus-two files ARE PR1-4's fixes, so R starts at 0 for all of them.

object_value.py is the one exception: #3680 named a SugarBody-generic-dispatch
debt there. Measured on top of main post-#3684 (which strengthened
FactoryBuildResult.sugar's generic binding as a side effect of unrelated wire-
seam work), the residual is a single reportUnknownVariableType on a
SugarBody[Unknown] local. It is pinned at its measured baseline, 1, rather
than faked to zero or silently excluded — the debt has a name and a count,
and this tooth stops it from growing.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "sugar_lift_py_tests"

# The closed-to-zero frontier: #3662's six hierarchy-edge files plus the two
# lift-report/source-memento DTOs #3661 (PR4) closed the dict[str, Any]
# fallback on.
STRICT_TARGETS: dict[str, Path] = {
    "context/factory_build_context.py": SRC / "context" / "factory_build_context.py",
    "sugar_body/sugar_body.py": SRC / "sugar_body" / "sugar_body.py",
    "factory/factory_build_result.py": SRC / "factory" / "factory_build_result.py",
    "effect/factory_gap_effect.py": SRC / "effect" / "factory_gap_effect.py",
    "floor/floor_value.py": SRC / "floor" / "floor_value.py",
    "floor/floor_dispatch_surface.py": SRC / "floor" / "floor_dispatch_surface.py",
    "kit_rpc/lift_report_payload_dto.py": SRC
    / "kit_rpc"
    / "lift_report_payload_dto.py",
    "kit_rpc/source_memento_dto.py": SRC / "kit_rpc" / "source_memento_dto.py",
    # Named debt, not silently excluded: see module docstring and #3680.
    "floor/object_value.py": SRC / "floor" / "object_value.py",
}

EXPECTED_STRICT_ERRORS: dict[str, int] = {
    "context/factory_build_context.py": 0,
    "sugar_body/sugar_body.py": 0,
    "factory/factory_build_result.py": 0,
    "effect/factory_gap_effect.py": 0,
    "floor/floor_value.py": 0,
    "floor/floor_dispatch_surface.py": 0,
    "kit_rpc/lift_report_payload_dto.py": 0,
    "kit_rpc/source_memento_dto.py": 0,
    "floor/object_value.py": 1,
}


@dataclass(frozen=True)
class StrictFileResult:
    target: str
    errors: int
    files_analyzed: int
    diagnostics: tuple[str, ...]


def test_strict_pyright_error_counts_match_ratchet() -> None:
    observed = {
        target: result
        for target in STRICT_TARGETS
        if (result := _run_pyright_strict(target))
    }
    failures = _ratchet_failures(
        {target: result.errors for target, result in observed.items()},
        EXPECTED_STRICT_ERRORS,
    )

    assert not failures, _render_report(observed, failures)


def test_strict_ratchet_rejects_new_errors_in_clean_file() -> None:
    failures = _ratchet_failures(
        {"floor/floor_value.py": 1},
        {"floor/floor_value.py": 0},
    )

    assert failures == [
        "floor/floor_value.py: observed 1 strict pyright error(s), expected at "
        "most 0; new type error introduced"
    ]


def test_strict_ratchet_rejects_stale_pin() -> None:
    failures = _ratchet_failures(
        {"floor/object_value.py": 40},
        {"floor/object_value.py": 52},
    )

    assert failures == [
        "floor/object_value.py: observed 40 strict pyright error(s), expected "
        "52; stale pin, lower EXPECTED_STRICT_ERRORS"
    ]


def test_pinned_debt_at_exact_count_stays_green() -> None:
    assert (
        _ratchet_failures({"floor/object_value.py": 52}, {"floor/object_value.py": 52})
        == []
    )


def _run_pyright_strict(target: str) -> StrictFileResult:
    path = STRICT_TARGETS[target]
    config = json.loads((ROOT / "pyrightconfig.json").read_text())
    config["typeCheckingMode"] = "strict"
    strict_config_path = ROOT / "pyrightconfig.strict-ratchet.json"
    strict_config_path.write_text(json.dumps(config))
    try:
        env = dict(os.environ)
        env["PYTHONPATH"] = _with_src_on_pythonpath(env.get("PYTHONPATH", ""))
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "pyright",
                "--project",
                str(strict_config_path),
                "--outputjson",
                str(path),
            ],
            cwd=ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    finally:
        strict_config_path.unlink(missing_ok=True)
    if proc.returncode not in {0, 1}:
        raise AssertionError(
            f"pyright --strict failed for {target} with exit {proc.returncode}\n"
            f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"pyright did not emit JSON for {target}\n"
            f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        ) from exc
    diagnostics = tuple(
        f"{Path(item['file']).relative_to(ROOT)}:{item['range']['start']['line'] + 1}: "
        f"{item['message']}"
        for item in payload.get("generalDiagnostics", ())
    )
    summary = payload["summary"]
    return StrictFileResult(
        target=target,
        errors=int(summary["errorCount"]),
        files_analyzed=int(summary["filesAnalyzed"]),
        diagnostics=diagnostics,
    )


def _ratchet_failures(observed: dict[str, int], expected: dict[str, int]) -> list[str]:
    failures: list[str] = []
    for target, expected_count in expected.items():
        actual = observed[target]
        if actual > expected_count:
            failures.append(
                f"{target}: observed {actual} strict pyright error(s), expected "
                f"at most {expected_count}; new type error introduced"
            )
        elif actual < expected_count:
            failures.append(
                f"{target}: observed {actual} strict pyright error(s), expected "
                f"{expected_count}; stale pin, lower EXPECTED_STRICT_ERRORS"
            )
    return failures


def _render_report(
    observed: dict[str, StrictFileResult],
    failures: list[str],
) -> str:
    lines = ["strict pyright ratchet failures:", *failures, "", "R(strict-edge-files):"]
    for target, result in observed.items():
        lines.append(
            f"  {target}: {result.errors} "
            f"(files={result.files_analyzed}, pin={EXPECTED_STRICT_ERRORS[target]})"
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
