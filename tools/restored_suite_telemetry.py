#!/usr/bin/env python3
"""Validate a completed restored-suite run and render its telemetry vector."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


_TERMINAL_ROW = re.compile(
    r"^(?:FAILED|ERROR) "
    r"(?:implementations/python/sugar-lift-py-tests/)?(tests/[^: ]+)",
    re.MULTILINE,
)
_COUNT = re.compile(r"(?P<count>\d+) (?P<kind>failed|errors?)\b")
_SUMMARY = re.compile(
    r"^.*(?:\d+ passed|\d+ failed|\d+ errors?|\d+ skipped).* in [0-9.]+s.*$",
    re.MULTILINE,
)


def restored_suite_vector(path: Path, *, pytest_exit: int) -> tuple[int, int, int]:
    if pytest_exit not in {0, 1}:
        raise ValueError(
            f"restored suite did not complete: pytest exit={pytest_exit}; "
            "only completed green or test-red runs mint telemetry"
        )
    text = path.read_text(encoding="utf-8")
    summaries = _SUMMARY.findall(text)
    if not summaries:
        raise ValueError("restored suite log has no pytest terminal summary")
    counts = {"failed": 0, "errors": 0}
    for match in _COUNT.finditer(summaries[-1]):
        kind = match.group("kind")
        counts["errors" if kind.startswith("error") else "failed"] = int(
            match.group("count")
        )
    modules = set(_TERMINAL_ROW.findall(text))
    if counts["failed"] + counts["errors"] and not modules:
        raise ValueError("red restored suite summary has no terminal module rows")
    return counts["failed"], counts["errors"], len(modules)


def markdown(run_url: str, vector: tuple[int, int, int]) -> str:
    failed, errors, modules = vector
    return (
        "## Restored-suite CI scoreboard\n\n"
        f"- failed: {failed}\n"
        f"- errors: {errors}\n"
        f"- affected modules: {modules}\n"
        f"- run: {run_url}\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--pytest-exit", type=int, required=True)
    parser.add_argument("--run-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rendered = markdown(
        args.run_url,
        restored_suite_vector(args.log, pytest_exit=args.pytest_exit),
    )
    args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
