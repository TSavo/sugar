from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping

from .command_result import CommandResult

RunCommand = Callable[[list[str], Path, dict[str, str]], CommandResult]


def mint_recovered_frontier(
    *,
    label: str,
    sugar_bin: Path,
    workspace: Path,
    root: Path,
    env: dict[str, str],
    output_dir: Path,
    runner: RunCommand,
) -> Mapping[str, Any]:
    """Run the one sanctioned recovered-construction-audit CLI lane."""
    frontier_path = output_dir / "frontier.json"
    result = runner(
        [
            os.fspath(sugar_bin),
            "lift",
            "--audit-frontier",
            "--continue-on-construction-gaps",
            "-o",
            os.fspath(frontier_path),
            os.fspath(workspace),
        ],
        root,
        env,
    )
    receipt = output_dir / "wall.frontier.txt"
    receipt.write_text(
        result.stdout
        + ("\n" if result.stdout and result.stderr else "")
        + result.stderr,
        encoding="utf-8",
    )
    if not frontier_path.is_file():
        combined = result.stdout + result.stderr
        tail = combined[-4000:] if combined else "<no output captured>"
        raise RuntimeError(
            f"{label} recovered frontier failed without frontier.json "
            f"exit={result.returncode}; last words follow:\n{tail}"
        )
    try:
        payload = json.loads(frontier_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{label} frontier.json was not valid JSON: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise RuntimeError(f"{label} frontier.json must be a JSON object")
    if payload.get("kind") != "recovered-construction-audit":
        raise RuntimeError(f"{label} frontier artifact has the wrong kind")
    if payload.get("recoveryOverride") is not True:
        raise RuntimeError(f"{label} frontier artifact lacks recovery override")
    for field in ("panics", "suppressedDescendants", "effects"):
        if not isinstance(payload.get(field), list):
            raise RuntimeError(f"{label} frontier artifact field `{field}` must be a list")
    return payload
