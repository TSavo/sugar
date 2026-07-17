#!/usr/bin/env python3
"""Validate a recovered wall frontier and render its conservation vector.

#4263: the post-merge conservation instrument reports the full bucket vector
(constructed / mandatory_panics / suppressed_descendants / typed_effects /
silent) so Delta R can be read run-to-run against the #4102 ledger. A lower
panic count alone is not evidence.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any


def _load_conservation_diff():
    path = Path(__file__).resolve().with_name("wall_conservation_diff.py")
    spec = importlib.util.spec_from_file_location("wall_conservation_diff", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_DIFF = _load_conservation_diff()


def frontier_vector(path: Path) -> tuple[int, int, int]:
    """Legacy three-lane tuple (panics, suppressed, effects) for callers."""
    vector = conservation_vector(path)
    return (
        vector["mandatory_panics"],
        vector["suppressed_descendants"],
        vector["typed_effects"],
    )


def conservation_vector(
    frontier_path: Path, summary_path: Path | None = None
) -> dict[str, int]:
    return _DIFF.conservation_vector(frontier_path, summary_path)


def markdown(
    wall: str,
    run_url: str,
    vector: tuple[int, int, int] | dict[str, int],
    *,
    summary_path: Path | None = None,
) -> str:
    if isinstance(vector, tuple):
        independent, suppressed, effects = vector
        body = (
            f"## {wall} wall telemetry\n\n"
            f"- independent: {independent}\n"
            f"- suppressed: {suppressed}\n"
            f"- effects: {effects}\n"
            f"- run: {run_url}\n"
        )
        # Dual-read: keep legacy lines and append the closed conservation
        # vector once callers pass a dict (or when summary is available).
        return body
    return conservation_markdown(wall, run_url, vector)


def conservation_markdown(
    wall: str, run_url: str, vector: dict[str, int]
) -> str:
    lines = [
        f"## {wall} wall conservation vector",
        "",
        f"- schema: `{_DIFF.SCHEMA}`",
        f"- constructed: {vector['constructed']}",
        f"- mandatory_panics: {vector['mandatory_panics']}",
        f"- suppressed_descendants: {vector['suppressed_descendants']}",
        f"- typed_effects: {vector['typed_effects']}",
        f"- silent: {vector['silent']} (floor: must be 0)",
        f"- source_files_enumerated: {vector['source_files_enumerated']}",
        f"- source_bodies_demanded: {vector['source_bodies_demanded']}",
        f"- audit_leaves_completed: {vector['audit_leaves_completed']}",
        f"- run: {run_url}",
        "",
        "<!-- sugar.wall.conservation-vector",
        json.dumps(
            {
                "schema": _DIFF.SCHEMA,
                "wall": wall,
                "vector": vector,
                "run": run_url,
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
        "-->",
        "",
    ]
    return "\n".join(lines)


def parse_ledger_vector(comment_body: str, wall: str) -> dict[str, int] | None:
    """Extract the most recent machine vector for ``wall`` from a ledger comment."""
    marker = "<!-- sugar.wall.conservation-vector"
    if marker not in comment_body:
        # Legacy three-lane comments are not a full vector; refuse rather than
        # invent constructed/silent from partial telemetry.
        return None
    start = comment_body.find(marker)
    payload_start = comment_body.find("\n", start)
    if payload_start < 0:
        return None
    payload_start += 1
    end = comment_body.find("-->", payload_start)
    if end < 0:
        return None
    raw = comment_body[payload_start:end].strip()
    try:
        payload: dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if payload.get("wall") != wall:
        return None
    vector = payload.get("vector")
    if not isinstance(vector, dict):
        return None
    required = _DIFF.BUCKETS + _DIFF.CENSUS_AXES
    out: dict[str, int] = {}
    for key in required:
        value = vector.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            return None
        out[key] = value
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frontier", type=Path, required=True)
    parser.add_argument("--summary", type=Path, default=None)
    parser.add_argument("--wall", required=True)
    parser.add_argument("--run-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--vector-json-out",
        type=Path,
        default=None,
        help="write machine-readable conservation vector for ledger delta",
    )
    args = parser.parse_args()
    vector = conservation_vector(args.frontier, args.summary)
    rendered = conservation_markdown(args.wall, args.run_url, vector)
    args.output.write_text(rendered, encoding="utf-8")
    if args.vector_json_out is not None:
        args.vector_json_out.write_text(
            json.dumps(
                {
                    "schema": _DIFF.SCHEMA,
                    "wall": args.wall,
                    "vector": vector,
                    "run": args.run_url,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
