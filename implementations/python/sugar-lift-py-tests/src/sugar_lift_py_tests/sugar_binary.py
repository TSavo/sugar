from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path
from typing import Mapping

from sugar_lift_py_tests.repo_root import resolve_repo_root


def monorepo_root() -> Path:
    """Monorepo root via the one resolve door — never parents[N]."""
    return resolve_repo_root()


def sugarbin_path() -> Path:
    return monorepo_root() / "bin" / "sugarbin"


def sugarbin_windows_path() -> Path:
    return monorepo_root() / "bin" / "sugarbin.ps1"


subprocess_run = subprocess.run

# How long the suite waits for `bin/sugarbin` to hand back a binary. The wait is
# real work only on the build rung: every worktree owns its own cargo build
# directory but the box is shared, so a peer holding that directory's lock
# ("Blocking waiting for file lock") stalls resolution for the whole budget.
DEFAULT_RESOLVE_TIMEOUT_SECONDS = 600.0


class SugarBinaryResolutionError(RuntimeError):
    pass


def resolve_timeout_seconds(env: Mapping[str, str] | None = None) -> float:
    """The resolution budget, overridable for sweeps that must bound the wait."""
    source = os.environ if env is None else env
    raw = source.get("SUGAR_BINARY_RESOLVE_TIMEOUT_SECONDS")
    if raw is None or not raw.strip():
        return DEFAULT_RESOLVE_TIMEOUT_SECONDS
    try:
        seconds = float(raw)
    except ValueError as exc:
        raise SugarBinaryResolutionError(
            "SUGAR_BINARY_RESOLVE_TIMEOUT_SECONDS must be a positive number of "
            f"seconds, got {raw!r}"
        ) from exc
    if seconds <= 0:
        raise SugarBinaryResolutionError(
            "SUGAR_BINARY_RESOLVE_TIMEOUT_SECONDS must be a positive number of "
            f"seconds, got {raw!r}"
        )
    return seconds


def sugarbin_route(*, os_name: str, hostname: str) -> str:
    """Select acquisition topology without attempting acquisition."""
    if os_name == "nt" and hostname.casefold() == "battleaxe":
        return "battleaxe-native"
    if os_name == "nt":
        return "windows-broker"
    return "posix-broker"


def current_os_name() -> str:
    """The platform family this process is running as.

    Exists so a test can substitute the routing input WITHOUT patching
    ``os.name`` itself. ``os.name`` is process-global and ``pathlib.Path.__new__``
    dispatches on it, so patching it makes every ``Path`` in the interpreter --
    including pytest's own reporter -- a ``WindowsPath``, which aborts the
    session. Patch this function instead.
    """
    return os.name


def resolve_sugar_binary(
    *,
    env: Mapping[str, str] | None = None,
    profile: str = "release",
) -> Path:
    child_env = dict(os.environ if env is None else env)
    route = sugarbin_route(os_name=current_os_name(), hostname=platform.node())
    if route == "battleaxe-native":
        command = [
            "powershell.exe",
            "-NoProfile",
            "-File",
            str(sugarbin_windows_path()),
            "-Profile",
            profile,
        ]
    elif route == "windows-broker":
        child_env["SUGAR_WINDOWS_SCRIPT"] = str(sugarbin_path())
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
        command = [str(sugarbin_path()), "--profile", profile]
    timeout = resolve_timeout_seconds(child_env)
    try:
        completed = subprocess_run(
            command,
            cwd=monorepo_root(),
            env=child_env,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        # A bare TimeoutExpired escaping here is the worst failure this module
        # has. `resolve_sugar_binary` is called from a session-scoped autouse
        # fixture, so an exception type the fixture does not catch errors EVERY
        # collected test with one identical traceback -- a whole-suite red that
        # reads like a mass regression and is really one stalled subprocess.
        # Name it as a resolution failure so the fixture exits once, loudly.
        raise SugarBinaryResolutionError(
            f"bin/sugarbin did not resolve a {profile} sugar binary within "
            f"{timeout:g}s.\n"
            "The build rung waits on the Rust build-directory lock, which a "
            "peer process on this box may hold for minutes. Prebuild the "
            "binary, or set SUGAR_BINARY_ALLOW_BUILD=0 to refuse the build rung "
            "and fail fast on a missing artifact, or raise "
            "SUGAR_BINARY_RESOLVE_TIMEOUT_SECONDS if the wait is expected."
        ) from exc
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
