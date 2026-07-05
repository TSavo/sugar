from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Mapping

ROOT = Path(__file__).resolve().parents[5]
SUGARBIN = ROOT / "bin" / "sugarbin"

subprocess_run = subprocess.run


class SugarBinaryResolutionError(RuntimeError):
    pass


def resolve_sugar_binary(
    *,
    env: Mapping[str, str] | None = None,
    profile: str = "release",
) -> Path:
    completed = subprocess_run(
        [str(SUGARBIN), "--profile", profile],
        cwd=ROOT,
        env=dict(os.environ if env is None else env),
        text=True,
        capture_output=True,
        check=False,
        timeout=600,
    )
    if completed.returncode != 0:
        raise SugarBinaryResolutionError(
            "bin/sugarbin failed to resolve a sugar binary\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        raise SugarBinaryResolutionError(
            "bin/sugarbin must print exactly one binary path to stdout\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return Path(lines[0])
