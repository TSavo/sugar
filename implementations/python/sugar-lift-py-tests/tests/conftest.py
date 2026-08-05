# SPDX-License-Identifier: MIT OR Apache-2.0
import os
import subprocess
import sys
from pathlib import Path

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = _HERE
while _ROOT != os.path.dirname(_ROOT) and not (
    os.path.isdir(os.path.join(_ROOT, "implementations"))
    and os.path.isdir(os.path.join(_ROOT, "tests"))
):
    _ROOT = os.path.dirname(_ROOT)
if os.path.join(_ROOT, "tests") not in sys.path:
    sys.path.insert(0, os.path.join(_ROOT, "tests"))

from checkout_resolution import pin_checkout  # noqa: E402

# Pin this package's sources to THIS checkout before anything imports them.
# Without the pin these tests resolve whatever editable install the machine
# happens to have -- which does not fail, it passes about the wrong code.
pin_checkout(__file__, siblings=())

from sugar_lift_py_tests.sugar_binary import (  # noqa: E402
    SugarBinaryResolutionError,
    resolve_sugar_binary,
)
from claim_mass_corpus import DATETIME_SHA256  # noqa: E402

# `tests/vendor/**` is hash-pinned LIFT CORPUS, not this package's test suite.
# Those files are third-party sources (cpython datetime.py, itsdangerous /
# numpy / pandas / requests test modules) that the suite reads as BYTES and
# parses as AST — see `claim_mass_corpus.ClaimMassPin` and the sha256 pins in
# `tests/claim_mass_tripwires`/`cpython_311_datetime_path`. They are never
# imported by us, and their sha256 pins mean we may not edit them to add an
# `importorskip` guard.
#
# Because they are named `test_*.py`, pytest was collecting them as OUR tests
# and IMPORTING them. `tests/vendor/itsdangerous-2.2.0/test_serializer.py`
# imports `itsdangerous` at module scope, so collection of the ENTIRE package
# aborted with `ModuleNotFoundError: itsdangerous` whenever that third-party
# package was absent — hiding ~1165 real tests behind one corpus file. The
# same trap is armed for numpy/pandas/requests.
#
# Corpus is data. Data does not get collected as tests.
collect_ignore_glob = ["vendor/*/*.py"]

_SUGAR_PROJECT_SUBCOMMANDS = frozenset({"mint", "prove", "lift", "verify"})


def _is_sugar_project_cli(cmd: object) -> bool:
    """True when argv is a sugar mint/prove/lift/verify against a project."""
    if not isinstance(cmd, (list, tuple)) or not cmd:
        return False
    parts = [str(part) for part in cmd]
    for index, part in enumerate(parts):
        name = Path(part).name
        # Match: `sugar`, stamped `sugar-darwin-…`/`sugar-linux-…`, and any
        # other resolved binary whose basename starts with `sugar-` but is not
        # a non-CLI helper (sugarbin, sugar-ir-*, sugar-walk-rpc, …). Project
        # subcommands mint/prove/lift/verify only appear on the main CLI.
        is_main_cli = name == "sugar" or (
            name.startswith("sugar-")
            and not name.startswith("sugar-ir-")
            and name
            not in {
                "sugarbin",
                "sugar-walk-rpc",
                "sugar-lsp",
                "sugar-ra-oracle",
            }
        )
        if is_main_cli:
            if (
                index + 1 < len(parts)
                and parts[index + 1] in _SUGAR_PROJECT_SUBCOMMANDS
            ):
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
def _isolate_process_resident_files():
    """One test, one residency (#7364). Cross-test sharing is unrepresentable.

    The process-resident file cache in ``sugar_source_tree`` is keyed by
    (content CID, workspace-RELATIVE filename), so byte-identical fixture source
    under the same relative name collides across tests and distinct ``tmp_path``
    gives ZERO isolation. ``_prepare_uncached`` -- MaterializeModule plus the
    unit's relation tables -- runs only on a MISS, so a later test can inherit a
    unit an earlier test already mutated.

    False red is merely expensive. False GREEN is the reason this is autouse: a
    test expecting a refusal, handed an already-refusing unit, passes without
    exercising its own mechanism, and that green cannot be told from a real one.

    Unconditional by design -- an opt-out marker would reinstate the silent
    default this closes. Residency is a within-test property; the prepare-count
    tests measure it inside one body and clear at entry already.

    Production behaviour is untouched: this resets only at the test boundary.
    """
    from sugar_source_tree.process_resident_file import clear_process_resident_files

    clear_process_resident_files()
    yield
    clear_process_resident_files()


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


# Hermetic CPython 3.11 datetime.py artifact (#4200). The full-file floor
# measurements pin this exact source; the hash makes corpus movement
# reproducible and a drifted copy loud instead of silently re-baselined.
_CPYTHON_311_DATETIME = Path(_HERE) / "vendor" / "cpython-3.11" / "datetime.py"
_CPYTHON_311_DATETIME_SHA256 = DATETIME_SHA256


@pytest.fixture(scope="session")
def cpython_311_datetime_path() -> Path:
    import hashlib

    data = _CPYTHON_311_DATETIME.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != _CPYTHON_311_DATETIME_SHA256:
        raise AssertionError(
            "vendored cpython-3.11 datetime.py drifted: "
            f"sha256={digest} expected={_CPYTHON_311_DATETIME_SHA256}; "
            "re-pin the hash together with every full-file locus assertion"
        )
    return _CPYTHON_311_DATETIME
