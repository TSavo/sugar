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


def sugarbin_route(*, os_name: str, hostname: str) -> str:
    """Select acquisition topology without attempting acquisition."""
    if os_name == "nt" and hostname.casefold() == "battleaxe":
        return "battleaxe-native"
    if os_name == "nt":
        return "windows-broker"
    return "posix-broker"


def resolve_sugar_binary(
    *,
    env: Mapping[str, str] | None = None,
    profile: str = "release",
) -> Path:
    child_env = dict(os.environ if env is None else env)
    route = sugarbin_route(os_name=os.name, hostname=platform.node())
    if route == "battleaxe-native":
        command = [
            "powershell.exe",
            "-NoProfile",
            "-File",
            str(SUGARBIN_WINDOWS),
            "-Profile",
            profile,
        ]
    elif route == "windows-broker":
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
