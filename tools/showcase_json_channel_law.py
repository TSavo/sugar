#!/usr/bin/env python3
"""Refuse showcase commands that merge diagnostics into JSON artifacts.

The Sugar CLI owns two channels: ``--json`` writes one structured document to
stdout, while diagnostics and named nonzero-exit explanations go to stderr.
A showcase may retain a combined ``.raw`` transcript and recover a receipt
from it deliberately.  A file named ``.json`` is different: it promises one
JSON document, so redirecting ``2>&1`` into it makes a valid CLI failure path
corrupt the consumer's structured input.

This is an open shell-script boundary, so the law remains an auditor rather
than pretending a Python type can constrain future shell redirections.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

from sugar_repo_root import resolve_repo_root


_JSON_ARTIFACT_REDIRECT = re.compile(
    r"(?<![0-9])>\s*[\"']?[^\s\"']*\.json[\"']?"
)


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    command: str


def _logical_shell_lines(text: str) -> Iterator[tuple[int, str]]:
    """Yield backslash-continued shell commands with their first line."""
    start = 1
    parts: list[str] = []
    for line_number, physical in enumerate(text.splitlines(), 1):
        if not parts:
            start = line_number
        stripped = physical.rstrip()
        if stripped.endswith("\\"):
            parts.append(stripped[:-1])
            continue
        parts.append(physical)
        yield start, " ".join(part.strip() for part in parts)
        parts = []
    if parts:
        yield start, " ".join(part.strip() for part in parts)


def findings_for_text(path: str, text: str) -> tuple[Finding, ...]:
    findings: list[Finding] = []
    for line_number, command in _logical_shell_lines(text):
        if (
            "--json" in command
            and "2>&1" in command
            and _JSON_ARTIFACT_REDIRECT.search(command)
        ):
            findings.append(
                Finding(path=path, line=line_number, command=command.strip())
            )
    return tuple(findings)


def scan(paths: Iterable[Path], root: Path) -> tuple[Finding, ...]:
    findings: list[Finding] = []
    for path in sorted(paths):
        findings.extend(
            findings_for_text(
                path.relative_to(root).as_posix(),
                path.read_text(encoding="utf-8"),
            )
        )
    return tuple(findings)


def _self_test() -> None:
    sample = """
tool prove . --json > .prove.json 2> .prove.stderr
tool prove . --json > .prove.raw 2>&1
tool prove . --json > .prove.json 2>&1
tool verify --json \\
  > \"$dir/.verify.json\" 2>&1
"""
    findings = findings_for_text("examples/planted/run.sh", sample)
    assert len(findings) == 2, findings
    assert findings[0].line == 4
    assert findings[1].line == 5


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        _self_test()
        print("showcase-json-channel-law self-test: pass")
        return 0

    root = resolve_repo_root(start=Path.cwd(), extra_starts=(Path(__file__),))
    findings = scan((root / "examples").glob("*/run.sh"), root)
    for finding in findings:
        print(
            "crime=structured-json-channel-corrupted "
            "owner=showcase-consumer "
            f"coordinate={finding.path}:{finding.line} "
            "observed=stderr-merged-into-json-artifact "
            "replacement=write-stdout-to-json-and-stderr-to-a-separate-diagnostic-file"
        )
    print(f"R_showcase_json_channel_corruption_count={len(findings)}")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
