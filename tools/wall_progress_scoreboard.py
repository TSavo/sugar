#!/usr/bin/env python3
"""Wall progress scoreboard (Lane B instrument 3).

Partial wall runs must produce a comparable receipt without requiring
frontier.json. Reads SUGAR_KIT_LOG transport.jsonl (+ wall.txt when present)
and emits progress.json so Δ progress is measured between deaths, not guessed
from 40MB engine.jsonl by hand.

This is not a green/red product gate. Incomplete is a measured state.
Exit 0 when progress is scored; exit 2 when inputs are unreadable.
Exit 1 only for --self-test failures.

See docs/analysis/ci-whack-a-mole-course-2026-07-15.md.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "sugar.wall.progress.v1"

DISCONNECT_RE = re.compile(
    r'stage=["\']?(?P<stage>[^\s"\']+)["\']?.*?message_id=(?P<mid>\d+)',
    re.DOTALL,
)
DISCONNECT_ALT_RE = re.compile(
    r"read_line\.disconnected|lift plugin transport disconnected|"
    r"plugin process ended without responding",
    re.IGNORECASE,
)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.is_file():
        return rows
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                rows.append(obj)
    return rows


def score_transport(rows: list[dict[str, Any]]) -> dict[str, Any]:
    completed = 0
    prev_mid: int | None = None
    generation_peaks: list[int] = []
    max_mid = 0
    last_file: str | None = None
    last_stage: str | None = None
    last_event: str | None = None
    last_method: str | None = None
    last_message_id: int | None = None
    definition_enters = 0
    enumeration_requests = 0

    for row in rows:
        event = row.get("event")
        stage = row.get("stage")
        if isinstance(stage, str):
            last_stage = stage
        if isinstance(event, str):
            last_event = event
        mid = row.get("message_id")
        if isinstance(mid, int):
            last_message_id = mid
            max_mid = max(max_mid, mid)
            if event == "response_about_to_send":
                completed += 1
                # Message ids reset when the resident generation rotates.
                # A drop after at least two successes is a generation peak.
                if prev_mid is not None and mid < prev_mid and prev_mid >= 2:
                    generation_peaks.append(prev_mid)
                prev_mid = mid
        file_name = row.get("file")
        if isinstance(file_name, str) and file_name:
            last_file = file_name
        method = row.get("method")
        if isinstance(method, str):
            last_method = method
        if event == "definition_enter":
            definition_enters += 1
        if event == "enumeration_request":
            enumeration_requests += 1

    if prev_mid is not None:
        generation_peaks.append(prev_mid)

    return {
        "completed_responses": completed,
        "generation_peaks": len(generation_peaks),
        "generation_peak_message_ids": generation_peaks[-12:],
        "max_message_id": max_mid,
        "last_file": last_file,
        "last_stage": last_stage,
        "last_event": last_event,
        "last_method": last_method,
        "last_message_id": last_message_id,
        "definition_enters": definition_enters,
        "enumeration_requests": enumeration_requests,
        "transport_events": len(rows),
    }


def score_wall_txt(text: str) -> dict[str, Any]:
    disconnect_stage: str | None = None
    message_id: int | None = None
    m = DISCONNECT_RE.search(text)
    if m:
        disconnect_stage = m.group("stage")
        message_id = int(m.group("mid"))
    elif DISCONNECT_ALT_RE.search(text):
        disconnect_stage = "read_line.disconnected"
    # Keep a short diagnostic tail.
    tail = text.strip()[-800:] if text.strip() else ""
    return {
        "disconnect_stage": disconnect_stage,
        "message_id_from_wall_txt": message_id,
        "wall_txt_tail": tail,
        "transport_failure": bool(
            "kind=transport" in text
            or "lift-plugin.transport" in text
            or DISCONNECT_ALT_RE.search(text)
        ),
    }


def build_progress(
    *,
    wall: str,
    wall_dir: Path,
    logs_dir: Path | None,
    exit_code: int | None,
) -> dict[str, Any]:
    logs = logs_dir or (wall_dir.parent / f"{wall}-wall-logs")
    # Common layout from workflow: .sugar/pandas-wall + .sugar/pandas-wall-logs
    transport_path = logs / "transport.jsonl"
    if not transport_path.is_file():
        # Fall back next to wall_dir
        alt = wall_dir / "transport.jsonl"
        if alt.is_file():
            transport_path = alt
    engine_path = logs / "engine.jsonl"
    wall_txt = wall_dir / "wall.txt"
    frontier_receipt = wall_dir / "wall.frontier.txt"
    frontier = wall_dir / "frontier.json"
    summary = wall_dir / "summary.json"

    transport_rows = _load_jsonl(transport_path)
    transport = score_transport(transport_rows)
    diagnostic_receipt = (
        frontier_receipt
        if frontier_receipt.is_file() and not frontier.is_file()
        else wall_txt
    )
    wall_meta = score_wall_txt(
        diagnostic_receipt.read_text(encoding="utf-8", errors="replace")
        if diagnostic_receipt.is_file()
        else ""
    )

    progress: dict[str, Any] = {
        "schema": SCHEMA,
        "wall": wall,
        "exit": exit_code,
        "has_frontier": frontier.is_file(),
        "has_summary": summary.is_file(),
        "has_wall_txt": wall_txt.is_file(),
        "diagnostic_receipt": (
            str(diagnostic_receipt) if diagnostic_receipt.is_file() else None
        ),
        "has_transport_log": transport_path.is_file(),
        "has_engine_log": engine_path.is_file(),
        "transport_log": str(transport_path) if transport_path.is_file() else None,
        "wall_dir": str(wall_dir),
        **transport,
        **wall_meta,
    }
    # Prefer wall.txt message_id when present (disconnect site).
    if progress.get("message_id_from_wall_txt") is not None:
        progress["message_id"] = progress["message_id_from_wall_txt"]
    else:
        progress["message_id"] = progress.get("last_message_id")
    if progress.get("disconnect_stage") is None and progress.get("last_stage"):
        # Incomplete run without explicit disconnect string.
        progress["disconnect_stage"] = progress.get("last_stage")
    return progress


def render_human(progress: dict[str, Any]) -> str:
    lines = [
        f"WALL PROGRESS SCOREBOARD ({progress.get('wall')})",
        f"schema: {progress.get('schema')}",
        f"exit: {progress.get('exit')}",
        f"completed_responses: {progress.get('completed_responses')}",
        f"generation_peaks: {progress.get('generation_peaks')}",
        f"max_message_id: {progress.get('max_message_id')}",
        f"last_file: {progress.get('last_file')}",
        f"disconnect_stage: {progress.get('disconnect_stage')}",
        f"message_id: {progress.get('message_id')}",
        f"has_frontier: {progress.get('has_frontier')}",
        f"definition_enters: {progress.get('definition_enters')}",
        f"enumeration_requests: {progress.get('enumeration_requests')}",
    ]
    tail = progress.get("wall_txt_tail") or ""
    if tail:
        lines.append("wall_txt_tail:")
        lines.append(tail)
    return "\n".join(lines) + "\n"


def self_test() -> int:
    with tempfile.TemporaryDirectory(prefix="wall-progress-") as tmp:
        root = Path(tmp)
        wall_dir = root / "pandas-wall"
        logs_dir = root / "pandas-wall-logs"
        wall_dir.mkdir()
        logs_dir.mkdir()
        transport = logs_dir / "transport.jsonl"
        # Two generations peaking at 3, then mid-gen disconnect narrative.
        rows = []
        for gen in range(2):
            for mid in range(1, 4):
                rows.append(
                    {
                        "event": "request_received",
                        "message_id": mid,
                        "method": "sugar.enumerate",
                        "stage": "dispatch",
                    }
                )
                rows.append(
                    {
                        "event": "response_about_to_send",
                        "message_id": mid,
                        "stage": "stdout.write",
                        "file": f"core/file{mid}.py",
                    }
                )
        rows.append(
            {
                "event": "request_received",
                "message_id": 2,
                "method": "sugar.enumerate",
                "stage": "dispatch",
            }
        )
        rows.append(
            {
                "event": "definition_enter",
                "stage": "lift_file.definition",
                "file": "core/indexes/multi.py",
                "message_id": 2,
            }
        )
        transport.write_text(
            "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8"
        )
        (wall_dir / "wall.txt").write_text(
            "stale initial fail-fast FactoryPanic\n",
            encoding="utf-8",
        )
        (wall_dir / "wall.frontier.txt").write_text(
            'ERROR stage="read_line.disconnected" message_id=2 '
            "plugin process ended without responding\n",
            encoding="utf-8",
        )
        progress = build_progress(
            wall="pandas",
            wall_dir=wall_dir,
            logs_dir=logs_dir,
            exit_code=1,
        )
        if progress["completed_responses"] != 6:
            print(
                f"FAIL: expected 6 completed responses, got {progress['completed_responses']}",
                file=sys.stderr,
            )
            return 1
        if progress["generation_peaks"] < 2:
            print(
                f"FAIL: expected ≥2 generation peaks, got {progress['generation_peaks']}",
                file=sys.stderr,
            )
            return 1
        if progress["last_file"] != "core/indexes/multi.py":
            print(
                f"FAIL: last_file wrong: {progress['last_file']}",
                file=sys.stderr,
            )
            return 1
        if progress["disconnect_stage"] != "read_line.disconnected":
            print(
                f"FAIL: disconnect_stage wrong: {progress['disconnect_stage']}",
                file=sys.stderr,
            )
            return 1
        if progress["message_id"] != 2:
            print(
                f"FAIL: message_id wrong: {progress['message_id']}",
                file=sys.stderr,
            )
            return 1
        if not str(progress["diagnostic_receipt"]).endswith("wall.frontier.txt"):
            print(
                "FAIL: incomplete recovered lane must own the diagnostic receipt",
                file=sys.stderr,
            )
            return 1
        if progress["has_frontier"] is not False:
            print("FAIL: has_frontier should be false", file=sys.stderr)
            return 1
        if progress["schema"] != SCHEMA:
            print("FAIL: schema mismatch", file=sys.stderr)
            return 1

    print("PASS: wall progress scoreboard scores partial runs")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--wall", default="pandas")
    parser.add_argument(
        "--wall-dir",
        type=Path,
        default=None,
        help="directory with wall.txt / frontier.json (default: .sugar/<wall>-wall)",
    )
    parser.add_argument(
        "--logs-dir",
        type=Path,
        default=None,
        help="directory with transport.jsonl / engine.jsonl",
    )
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--exit-code", type=int, default=None)
    parser.add_argument(
        "--json-only",
        action="store_true",
        help="print progress.json only (no human summary)",
    )
    args = parser.parse_args(argv)

    if args.self_test:
        return self_test()

    wall_dir = args.wall_dir or (ROOT / ".sugar" / f"{args.wall}-wall")
    logs_dir = args.logs_dir or (ROOT / ".sugar" / f"{args.wall}-wall-logs")
    if not wall_dir.is_dir() and not logs_dir.is_dir():
        print(
            f"FAIL: neither wall-dir nor logs-dir exists: {wall_dir} / {logs_dir}",
            file=sys.stderr,
        )
        return 2

    progress = build_progress(
        wall=args.wall,
        wall_dir=wall_dir,
        logs_dir=logs_dir if logs_dir.is_dir() else None,
        exit_code=args.exit_code,
    )
    out = args.output or (wall_dir / "progress.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(progress, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if args.json_only:
        print(json.dumps(progress, indent=2, sort_keys=True))
    else:
        print(render_human(progress), end="")
        print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
