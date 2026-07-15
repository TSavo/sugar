from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path
from typing import Mapping

ROOT = Path(__file__).resolve().parents[5]
SUGARBIN = ROOT / "bin" / "sugarbin"
SUGARBIN_WINDOWS = ROOT / "bin" / "sugarbin.ps1"

subprocess_run = subprocess.run


class SugarBinaryResolutionError(RuntimeError):
    pass


def resolve_sugar_binary(
    *,
    env: Mapping[str, str] | None = None,
    profile: str = "release",
) -> Path:
    child_env = dict(os.environ if env is None else env)
    if os.name == "nt" and platform.node().casefold() == "battleaxe":
        command = [
            "powershell.exe",
            "-NoProfile",
            "-File",
            str(SUGARBIN_WINDOWS),
            "-Profile",
            profile,
        ]
    elif os.name == "nt":
        child_env["SUGAR_WINDOWS_SCRIPT"] = str(SUGARBIN)
        command = [
            "bash.exe",
            "-lc",
            'script="$(cygpath -u "$SUGAR_WINDOWS_SCRIPT" 2>/dev/null || '
            'wslpath -u "$SUGAR_WINDOWS_SCRIPT")"; '
            'exec "$script" --profile "$1"',
            "sugarbin",
            profile,
        ]
    else:
        command = [str(SUGARBIN), "--profile", profile]
    completed = subprocess_run(
        command,
        cwd=ROOT,
        env=child_env,
        text=True,
        capture_output=True,
        check=False,
        timeout=600,
    )
    if completed.returncode != 0:
        raise SugarBinaryResolutionError(
            "bin/sugarbin platform entrypoint failed to resolve a sugar binary\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        raise SugarBinaryResolutionError(
            "bin/sugarbin platform entrypoint must print exactly one binary path to stdout\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    return Path(lines[0])
