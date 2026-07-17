#!/usr/bin/env python3
"""Pull the prior conservation vector for a wall from the #4102 ledger.

Merged-main CI mints the current vector, then this tool extracts the most
recent prior machine vector for the same wall from issue comments so
wall_conservation_diff can print Delta R. Missing history is not a failure:
the first mint establishes the ledger baseline.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

# Reuse the telemetry parser so the HTML comment envelope has one owner.
import importlib.util


def _load_telemetry():
    path = Path(__file__).resolve().with_name("wall_frontier_telemetry.py")
    spec = importlib.util.spec_from_file_location("wall_frontier_telemetry", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fetch_issue_comments(repo: str, issue: int) -> list[dict]:
    raw = subprocess.check_output(
        [
            "gh",
            "api",
            f"repos/{repo}/issues/{issue}/comments",
            "--paginate",
        ],
        text=True,
    )
    # --paginate may concatenate pages as a single JSON array or multiple.
    raw = raw.strip()
    if not raw:
        return []
    try:
        payload = json.loads(raw)
        if isinstance(payload, list):
            return payload
    except json.JSONDecodeError:
        pass
    # Multiple arrays concatenated: split by `]\n[` boundaries.
    chunks: list[dict] = []
    for part in raw.replace("][", "]\n[").splitlines():
        part = part.strip()
        if not part:
            continue
        page = json.loads(part)
        if isinstance(page, list):
            chunks.extend(page)
    return chunks


def previous_vector(
    *, repo: str, issue: int, wall: str, skip_run: str | None = None
) -> dict | None:
    telemetry = _load_telemetry()
    comments = fetch_issue_comments(repo, issue)
    # Newest last in GitHub API order; walk reverse for most recent match.
    for comment in reversed(comments):
        body = comment.get("body")
        if not isinstance(body, str):
            continue
        vector = telemetry.parse_ledger_vector(body, wall)
        if vector is None:
            continue
        # Prefer the embedded run URL envelope when skip_run is set.
        marker = "<!-- sugar.wall.conservation-vector"
        if marker in body and skip_run:
            start = body.find(marker)
            payload_start = body.find("\n", start) + 1
            end = body.find("-->", payload_start)
            if end > payload_start:
                try:
                    envelope = json.loads(body[payload_start:end].strip())
                except json.JSONDecodeError:
                    envelope = {}
                if envelope.get("run") == skip_run:
                    continue
        return {
            "schema": "sugar.wall.conservation-vector.v1",
            "wall": wall,
            "vector": vector,
            "comment_url": comment.get("html_url"),
            "comment_id": comment.get("id"),
        }
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--issue", type=int, default=4102)
    parser.add_argument("--wall", required=True)
    parser.add_argument("--skip-run", default=None)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        found = previous_vector(
            repo=args.repo,
            issue=args.issue,
            wall=args.wall,
            skip_run=args.skip_run,
        )
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"wall-ledger-previous-vector: {exc}", file=sys.stderr)
        return 2
    if found is None:
        print(f"no prior {args.wall} conservation vector on #{args.issue}")
        args.output.write_text("", encoding="utf-8")
        return 0
    args.output.write_text(
        json.dumps(found, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"prior {args.wall} vector from comment {found.get('comment_id')} "
        f"-> {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
