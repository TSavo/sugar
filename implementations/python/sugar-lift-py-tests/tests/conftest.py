# SPDX-License-Identifier: MIT OR Apache-2.0
import os
import subprocess
import sys
from pathlib import Path

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.normpath(os.path.join(_HERE, "..", "src"))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
# the tests dir itself, so per-sugar tests can import the shared `factory_reduce`
# harness module.
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from sugar_lift_py_tests.sugar_binary import (  # noqa: E402
    SugarBinaryResolutionError,
    resolve_sugar_binary,
)

_SUGAR_PROJECT_SUBCOMMANDS = frozenset({"mint", "prove", "lift", "verify"})


def _is_sugar_project_cli(cmd: object) -> bool:
    """True when argv is a sugar mint/prove/lift/verify against a project."""
    if not isinstance(cmd, (list, tuple)) or not cmd:
        return False
    parts = [str(part) for part in cmd]
    for index, part in enumerate(parts):
        name = Path(part).name
        if name == "sugar" or name.startswith("sugar-darwin") or name.startswith(
            "sugar-linux"
        ):
            if index + 1 < len(parts) and parts[index + 1] in _SUGAR_PROJECT_SUBCOMMANDS:
                return True
    return False


@pytest.fixture(scope="session", autouse=True)
def sugar_binary_handoff() -> str:
    try:
        sugar = resolve_sugar_binary()
    except SugarBinaryResolutionError as exc:
        pytest.exit(str(exc), returncode=2)
    os.environ["SUGAR_BIN"] = os.fspath(sugar)
    return os.fspath(sugar)


@pytest.fixture(autouse=True)
def refuse_non_hermetic_sugar_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail loud if any test shells out to sugar mint/prove/lift/verify without SUGAR_HOME.

    The suite's one door is `witness_harness.hermetic_sugar_env` /
    `run_sugar_cli`. A forgotten bare `subprocess.run([sugar, "mint", ...])`
    must be unable to leak ambient pool state — not merely discouraged.
    """
    real_run = subprocess.run

    def guarded_run(cmd, *args, **kwargs):  # type: ignore[no-untyped-def]
        if _is_sugar_project_cli(cmd):
            env = kwargs.get("env")
            if env is None:
                env = os.environ
            if not env.get("SUGAR_HOME"):
                raise AssertionError(
                    "sugar mint/prove/lift/verify invoked without SUGAR_HOME; "
                    "route through sugar_lift_py_tests.witness_harness.run_sugar_cli "
                    f"(or hermetic_sugar_env). cmd={cmd!r}"
                )
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", guarded_run)
