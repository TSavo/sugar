#!/usr/bin/env python3
"""Showcase verdict residue scoreboard (Lane A instrument A2).

A1 (kit import) is separate. A2 measures wrong *verdict class* and missing
receipt rows after kits import: expected discharged→refused, missing property
rows, mint failures, etc.

Modes:
  --self-test     planted shapes trip classification
  --from-log PATH classify a CI / make test-showcases log
  --from-dir PATH classify *.log files under a directory
  (default)       require --from-log or --from-dir

A2 = number of classified product-residue events (not runner-env, not A1).
Exit 1 when A2 > 0 (red while residue remains). Exit 0 when A2 = 0.
Exit 2 when no input was provided / unreadable.

See docs/analysis/ci-whack-a-mole-course-2026-07-15.md.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "sugar.showcase.verdict.v1"


@dataclass(frozen=True)
class Pattern:
    shape: str
    axis: str  # A1 | A2 | runner-env
    regex: re.Pattern[str]
    replacement: str


# Order matters: first match wins. A1 and runner-env are classified but do not
# count toward A2 residue.
PATTERNS: tuple[Pattern, ...] = (
    Pattern(
        "A1/kit-import-missing",
        "A1",
        re.compile(r"ModuleNotFoundError: No module named 'sugar_lift_"),
        "install sugar_lift_* via sticky venv / make build-python; preflight A1",
    ),
    Pattern(
        "runner-env/permission-denied",
        "runner-env",
        re.compile(r"Permission denied|PermissionError: \[Errno 13\]"),
        "fix runner environment; not a product verdict",
    ),
    Pattern(
        "A2/missing-property-rows",
        "A2",
        re.compile(
            r"no \w+ property rows in receipt|"
            r"no \w+ rows in prove receipt|"
            r"FAIL\([^)]+\): no \w+"
        ),
        "restore property emission / universe rows for the named surface",
    ),
    Pattern(
        "A2/expected-discharge-got-refused",
        "A2",
        re.compile(
            r"expected all (?:relevant )?consistency rows DISCHARGED|"
            r"expected all discharged, got \['refused'\]|"
            r"durable consistency statuses \['refused'|"
            r"expected the witness dimension to be VERIFIED|"
            r"expected witness discharge, got (?:refused|MISSING)|"
            r"expected dual unsatisfied, got \['refused'\]"
        ),
        "fix discharge path or honest refuse classification for the twin",
    ),
    Pattern(
        "A2/expected-verdict-mismatch",
        "A2",
        re.compile(
            r"sugar did not produce the expected verdict|"
            r"guard-shapes package must refuse|"
            r"lying discharge stdout flipped|"
            r"FAIL: expected "
        ),
        "align showcase twin expectation with actual prove/verify verdict",
    ),
    Pattern(
        "A2/mint-failed",
        "A2",
        re.compile(
            r"FAIL\((?:good|bad)\): mint|"
            r"FAIL: (?:vendor )?mint|"
            r"FAIL: missing forall-vampire claim row"
        ),
        "restore mint path / claim row emission for the showcase surface",
    ),
    Pattern(
        "A2/source-audit-delta-epsilon",
        "A2",
        re.compile(r"SOURCE AUDIT DELTA-EPSILON GATE FAILED"),
        "classify remaining source loci or adjust the showcase refuse surface",
    ),
)

# Accept plain make output and GitHub Actions log lines (timestamp/job prefix).
SHOWCASE_HEADER = re.compile(
    r"====\s+(?P<path>examples/\S+/(?:run\.sh|run-logo-receipt\.sh))\s+===="
)
SHOWCASE_FAIL_LINE = re.compile(
    r"====\s+(?P<label>\S+):\s+FAIL\s+====|"
    r"==== test-showcases FAIL:(?P<list>.+)===="
)
# Strip ANSI + GHA "jobnameUNKNOWN STEPtimestampZ " noise for matching.
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
GHA_PREFIX_RE = re.compile(
    r"^(?:.*?UNKNOWN STEP)?\d{4}-\d{2}-\d{2}T[\d:.]+Z\s+"
)


@dataclass(frozen=True)
class Hit:
    shape: str
    axis: str
    showcase: str
    detail: str
    replacement: str

    def to_json(self) -> dict[str, str]:
        return {
            "shape": self.shape,
            "axis": self.axis,
            "showcase": self.showcase,
            "detail": self.detail,
            "replacement": self.replacement,
        }


def classify_line(line: str, showcase: str) -> Hit | None:
    for pat in PATTERNS:
        m = pat.regex.search(line)
        if not m:
            continue
        detail = line.strip()
        if len(detail) > 240:
            detail = detail[:237] + "..."
        return Hit(
            shape=pat.shape,
            axis=pat.axis,
            showcase=showcase,
            detail=detail,
            replacement=pat.replacement,
        )
    return None


def _normalize_log_line(raw: str) -> str:
    line = ANSI_RE.sub("", raw)
    line = GHA_PREFIX_RE.sub("", line)
    return line


def classify_log(text: str) -> list[Hit]:
    hits: list[Hit] = []
    current = "<unknown>"
    seen: set[tuple[str, str, str]] = set()
    for raw in text.splitlines():
        line = _normalize_log_line(raw)
        header = SHOWCASE_HEADER.search(line)
        if header:
            current = header.group("path")
            continue
        fail_line = SHOWCASE_FAIL_LINE.search(line)
        if fail_line and fail_line.group("list"):
            # Bulk fail list — per-showcase hits already captured above.
            continue
        hit = classify_line(line, current)
        if hit is None:
            continue
        key = (hit.axis, hit.shape, hit.showcase)
        if key in seen:
            continue
        seen.add(key)
        hits.append(hit)
    return hits


def scoreboard(hits: list[Hit]) -> dict[str, object]:
    a1 = [h for h in hits if h.axis == "A1"]
    a2 = [h for h in hits if h.axis == "A2"]
    runner = [h for h in hits if h.axis == "runner-env"]
    by_shape: dict[str, int] = {}
    for h in a2:
        by_shape[h.shape] = by_shape.get(h.shape, 0) + 1
    return {
        "schema": SCHEMA,
        "A1": len(a1),
        "A2": len(a2),
        "runner_env": len(runner),
        "A2_by_shape": dict(sorted(by_shape.items())),
        "hits": [h.to_json() for h in hits],
    }


def render_human(payload: dict[str, object]) -> str:
    lines = [
        "SHOWCASE VERDICT SCOREBOARD",
        f"schema: {payload['schema']}",
        f"A1={payload['A1']}  A2={payload['A2']}  runner_env={payload['runner_env']}",
    ]
    by_shape = payload.get("A2_by_shape") or {}
    if by_shape:
        lines.append("A2_by_shape:")
        assert isinstance(by_shape, dict)
        for shape, count in by_shape.items():
            lines.append(f"  {count:4d}  {shape}")
    hits = payload.get("hits") or []
    a2_hits = [h for h in hits if isinstance(h, dict) and h.get("axis") == "A2"]
    if a2_hits:
        lines.append("A2 offenders (first match per showcase+shape):")
        for h in a2_hits:
            lines.append(f"  [{h['shape']}] {h['showcase']}")
            lines.append(f"    {h['detail']}")
            lines.append(f"    replacement: {h['replacement']}")
    if int(payload["A2"]) > 0:
        lines.append("FAIL: A2 must be 0 (every showcase verdict matches its twin law)")
    else:
        lines.append("PASS: A2=0 — no classified showcase verdict residue in input")
    return "\n".join(lines) + "\n"


def self_test() -> int:
    planted = """
==== examples/numpy-showcase/run.sh ====
ModuleNotFoundError: No module named 'sugar_lift_python_source'
==== examples/pandas-showcase/run.sh ====
FAIL: sugar did not produce the expected verdict.
==== examples/python-urlsafe-seam/run.sh ====
FAIL(good): no urlsafe_b64encode property rows in receipt
==== examples/std-core-showcase/run.sh ====
FAIL[good]: expected all relevant consistency rows DISCHARGED
==== examples/itsdangerous-token-padding/run.sh ====
FAIL: expected dual unsatisfied, got ['refused']
==== examples/python-literal-base64/run.sh ====
FAIL(good): mint
==== examples/rust-regex-membership/run.sh ====
SOURCE AUDIT DELTA-EPSILON GATE FAILED: R=2 unresolved source loci remain
==== examples/java-assertion-consistency/run.sh ====
==== java-assertion-consistency showcase: PASS ====
"""
    hits = classify_log(planted)
    payload = scoreboard(hits)
    if payload["A1"] != 1:
        print(f"FAIL: expected A1=1, got {payload['A1']}", file=sys.stderr)
        return 1
    if payload["A2"] < 5:
        print(
            f"FAIL: expected A2≥5 planted product residues, got {payload['A2']}: "
            f"{payload['A2_by_shape']}",
            file=sys.stderr,
        )
        return 1
    shapes = set(payload["A2_by_shape"])  # type: ignore[arg-type]
    needed = {
        "A2/missing-property-rows",
        "A2/expected-discharge-got-refused",
        "A2/expected-verdict-mismatch",
        "A2/mint-failed",
        "A2/source-audit-delta-epsilon",
    }
    missing = needed - shapes
    if missing:
        print(f"FAIL: planted shapes not classified: {missing}", file=sys.stderr)
        return 1
    # Clean log → A2=0
    clean = classify_log("==== examples/java-crc32-universe/run.sh ====\nPASS\n")
    if scoreboard(clean)["A2"] != 0:
        print("FAIL: clean log produced A2 residue", file=sys.stderr)
        return 1
    print("PASS: showcase verdict scoreboard classifies A1/A2 planted shapes")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--from-log", type=Path, default=None)
    parser.add_argument("--from-dir", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--json-only", action="store_true")
    args = parser.parse_args(argv)

    if args.self_test:
        return self_test()

    texts: list[str] = []
    if args.from_log is not None:
        if not args.from_log.is_file():
            print(f"FAIL: missing log {args.from_log}", file=sys.stderr)
            return 2
        texts.append(args.from_log.read_text(encoding="utf-8", errors="replace"))
    if args.from_dir is not None:
        if not args.from_dir.is_dir():
            print(f"FAIL: missing dir {args.from_dir}", file=sys.stderr)
            return 2
        for path in sorted(args.from_dir.rglob("*.log")):
            texts.append(path.read_text(encoding="utf-8", errors="replace"))
        for path in sorted(args.from_dir.rglob("*.txt")):
            texts.append(path.read_text(encoding="utf-8", errors="replace"))

    if not texts:
        print(
            "FAIL: provide --from-log PATH or --from-dir PATH (or --self-test)",
            file=sys.stderr,
        )
        return 2

    hits: list[Hit] = []
    for text in texts:
        hits.extend(classify_log(text))
    # Dedup across files
    seen: set[tuple[str, str, str]] = set()
    unique: list[Hit] = []
    for h in hits:
        key = (h.axis, h.shape, h.showcase)
        if key in seen:
            continue
        seen.add(key)
        unique.append(h)

    payload = scoreboard(unique)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    if args.json_only:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(render_human(payload), end="")
        if args.output is not None:
            print(f"wrote {args.output}")
    return 1 if int(payload["A2"]) > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
