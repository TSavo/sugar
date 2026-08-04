"""The immutable-venv guard inspects the venv, not ambient PYTHONPATH."""

from __future__ import annotations

import os
import subprocess
import venv
from pathlib import Path

from repo_root_test_support import resolve_repo_root

ROOT = resolve_repo_root()
GUARD = ROOT / "tools/refuse_first_party_venv_contamination.py"
PACKAGE = "sugar-lift-py-tests"


def _venv_python(path: Path) -> Path:
    venv.create(path, with_pip=False, clear=True)
    python = path / ("Scripts" if os.name == "nt" else "bin") / "python"
    assert python.is_file()
    return python


def _purelib(python: Path) -> Path:
    completed = subprocess.run(
        [str(python), "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(completed.stdout.strip())


def _run_guard(python: Path, *, pythonpath: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    if pythonpath is None:
        env.pop("PYTHONPATH", None)
    else:
        env["PYTHONPATH"] = str(pythonpath)
    return subprocess.run(
        [str(python), str(GUARD), PACKAGE],
        env=env,
        capture_output=True,
        text=True,
    )


def test_job_pythonpath_metadata_does_not_contaminate_venv(tmp_path: Path) -> None:
    """Checkout metadata visible only through job PYTHONPATH is not installed."""
    python = _venv_python(tmp_path / "venv")
    checkout_src = tmp_path / "checkout/src"
    metadata = checkout_src / "sugar_lift_py_tests.egg-info"
    metadata.mkdir(parents=True)
    (metadata / "PKG-INFO").write_text(
        "Metadata-Version: 2.1\nName: sugar-lift-py-tests\nVersion: 1\n",
        encoding="utf-8",
    )

    completed = _run_guard(python, pythonpath=checkout_src)

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "venv-contamination status=clean" in completed.stdout


def test_venv_local_first_party_distribution_is_refused(tmp_path: Path) -> None:
    """A first-party distribution physically installed in the venv stays red."""
    python = _venv_python(tmp_path / "venv")
    metadata = _purelib(python) / "sugar_lift_py_tests-1.dist-info"
    metadata.mkdir(parents=True)
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: sugar-lift-py-tests\nVersion: 1\n",
        encoding="utf-8",
    )

    completed = _run_guard(python)

    assert completed.returncode != 0
    combined = completed.stdout + completed.stderr
    assert "first-party package sugar-lift-py-tests present in venv" in combined
    assert str(metadata) in combined
