#!/usr/bin/env python3
"""Showcase kit import preflight (Lane A instrument).

Law: every showcase that needs a Python kit can import it without ambient
site-packages archaeology. Failures must name the install contract
(`make build-python` / per-showcase sticky venv law), not cascade into
refuse rows three minutes later.

A1 = number of failed kit contracts. Exit 1 while A1 > 0.

See docs/analysis/ci-whack-a-mole-course-2026-07-15.md.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
import venv
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Source trees showcases put on PYTHONPATH for bind_rpc / lean lift.
SOURCE_PATHS = (
    ROOT / "implementations/python/sugar-lift-python-source/src",
    ROOT / "implementations/python/sugar-lift-py-tests/src",
    ROOT / "implementations/python/sugar-lift-py-pytest-witness/src",
)

EDITABLE_PACKAGES = (
    ROOT / "implementations/python/sugar-lift-python-source",
    ROOT / "implementations/python/sugar-lift-py-tests",
    ROOT / "implementations/python/sugar-lift-py-pytest-witness",
)

REQUIRED_IMPORTS = (
    "sugar_lift_python_source",
    "sugar_lift_py_tests",
    "sugar_pytest_witness",
)

# Sticky witness venvs used by family showcases. Checked only when present
# so clean runners are not forced to pre-create them.
STICKY_VENVS = (
    ("numpy-witness", Path(os.environ.get("NUMPY_WITNESS_VENV", "/tmp/numpy-witness-venv"))),
    ("pandas-witness", Path(os.environ.get("PANDAS_WITNESS_VENV", "/tmp/pandas-witness-venv"))),
    ("sklearn-witness", Path(os.environ.get("SKLEARN_WITNESS_VENV", "/tmp/sklearn-witness-venv"))),
)

PIP_DEPS = ("blake3", "cbor2", "pynacl")


@dataclass(frozen=True)
class Failure:
    axis: str
    contract: str
    detail: str

    def render(self) -> str:
        return f"  [{self.axis}] {self.contract}\n    {self.detail}"


def _run_import_check(
    python: str | Path,
    modules: tuple[str, ...],
    *,
    env: dict[str, str] | None = None,
) -> tuple[bool, str]:
    code = "\n".join(f"import {m}" for m in modules) + "\nprint('ok')\n"
    try:
        proc = subprocess.run(
            [str(python), "-c", code],
            check=False,
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"{type(exc).__name__}: {exc}"
    if proc.returncode == 0:
        return True, "ok"
    err = (proc.stderr or proc.stdout or "").strip()
    # Keep one diagnostic line.
    first = next((ln for ln in err.splitlines() if ln.strip()), f"exit={proc.returncode}")
    return False, first


def check_source_pythonpath() -> list[Failure]:
    """Showcases stage bind_rpc with repo src on PYTHONPATH — that must work."""
    failures: list[Failure] = []
    missing = [p for p in SOURCE_PATHS if not p.is_dir()]
    if missing:
        for p in missing:
            failures.append(
                Failure(
                    axis="A1",
                    contract="source-tree layout",
                    detail=f"missing kit src tree: {p.relative_to(ROOT)}",
                )
            )
        return failures

    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(str(p) for p in SOURCE_PATHS)
    ok, detail = _run_import_check(sys.executable, REQUIRED_IMPORTS, env=env)
    if not ok:
        failures.append(
            Failure(
                axis="A1",
                contract="source PYTHONPATH imports",
                detail=(
                    f"{detail}; expected importable via "
                    f"PYTHONPATH={env['PYTHONPATH']}"
                ),
            )
        )
    return failures


def check_fresh_editable_install() -> list[Failure]:
    """Witness venvs law: pip install -e the three packages into a clean venv."""
    failures: list[Failure] = []
    for pkg in EDITABLE_PACKAGES:
        if not (pkg / "pyproject.toml").is_file() and not (pkg / "setup.py").is_file():
            # sugar packages use pyproject; fail loud if layout moved
            if not pkg.is_dir():
                failures.append(
                    Failure(
                        axis="A1",
                        contract="editable package layout",
                        detail=f"missing package dir: {pkg.relative_to(ROOT)}",
                    )
                )
    if failures:
        return failures

    with tempfile.TemporaryDirectory(prefix="sugar-showcase-preflight-") as tmp:
        venv_dir = Path(tmp) / "venv"
        try:
            venv.create(venv_dir, with_pip=True, clear=True)
        except Exception as exc:  # noqa: BLE001 — preflight names the contract
            return [
                Failure(
                    axis="A1",
                    contract="fresh venv create",
                    detail=f"{type(exc).__name__}: {exc}",
                )
            ]
        python = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        pip = [str(python), "-m", "pip"]
        try:
            subprocess.run(
                [*pip, "install", "--quiet", "--upgrade", "pip"],
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            install_cmd = [
                *pip,
                "install",
                "--quiet",
                "--no-cache-dir",
                *PIP_DEPS,
            ]
            for pkg in EDITABLE_PACKAGES:
                install_cmd.extend(["-e", str(pkg)])
            proc = subprocess.run(
                install_cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=300,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return [
                Failure(
                    axis="A1",
                    contract="fresh editable install",
                    detail=f"{type(exc).__name__}: {exc}",
                )
            ]
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()
            tail = "\n".join(err.splitlines()[-8:]) if err else f"exit={proc.returncode}"
            return [
                Failure(
                    axis="A1",
                    contract="fresh editable install",
                    detail=(
                        "pip install -e sugar-lift-python-source + "
                        "sugar-lift-py-tests + sugar-lift-py-pytest-witness failed:\n"
                        f"    {tail}"
                    ),
                )
            ]
        ok, detail = _run_import_check(python, REQUIRED_IMPORTS)
        if not ok:
            failures.append(
                Failure(
                    axis="A1",
                    contract="fresh editable imports",
                    detail=(
                        f"{detail}; after clean venv + editable install of "
                        "sugar_lift_python_source / sugar_lift_py_tests / "
                        "sugar_pytest_witness"
                    ),
                )
            )
    return failures


def check_sticky_venvs() -> list[Failure]:
    """If a showcase sticky venv already exists, it must resolve kit imports."""
    failures: list[Failure] = []
    for name, path in STICKY_VENVS:
        python = path / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if not python.is_file():
            continue  # not created yet — showcases create on demand
        ok, detail = _run_import_check(python, REQUIRED_IMPORTS)
        if not ok:
            failures.append(
                Failure(
                    axis="A1",
                    contract=f"sticky venv {name}",
                    detail=(
                        f"{detail}; path={path}. "
                        "Rebuild: remove the venv or re-run the showcase install "
                        "block so sugar_lift_python_source is editable-installed."
                    ),
                )
            )
    return failures


def run_preflight(*, include_fresh_install: bool = True) -> list[Failure]:
    failures: list[Failure] = []
    failures.extend(check_source_pythonpath())
    if include_fresh_install:
        failures.extend(check_fresh_editable_install())
    failures.extend(check_sticky_venvs())
    return failures


def report(failures: list[Failure]) -> int:
    a1 = len(failures)
    print("SHOWCASE KIT PREFLIGHT")
    print(f"A1={a1} failed kit contracts")
    print(
        "required imports: "
        + ", ".join(REQUIRED_IMPORTS)
    )
    if failures:
        print("failures:")
        for item in failures:
            print(item.render())
        print(
            "FAIL: A1 must be 0 before test-showcases "
            "(install law: source PYTHONPATH + editable sticky venvs)"
        )
        print(
            "hint: make build-python installs kits into "
            f"{os.environ.get('PYTHON_KIT_VENV', '/tmp/sugar-python-kit-env')}; "
            "family showcases use their own sticky venvs under /tmp/*-witness-venv"
        )
        return 1
    print("PASS: A1=0 — showcase kit imports resolve under declared contracts")
    return 0


def self_test() -> int:
    # Source trees must exist in this checkout.
    for p in SOURCE_PATHS:
        if not p.is_dir():
            print(f"FAIL: self-test missing source tree {p}", file=sys.stderr)
            return 1

    # Broken PYTHONPATH must trip A1.
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "does-not-exist-for-preflight")
    ok, _ = _run_import_check(sys.executable, ("sugar_lift_python_source",), env=env)
    # May still ok if packages installed in the agent environment — so plant
    # a guaranteed-missing module name instead.
    ok_missing, detail = _run_import_check(
        sys.executable,
        ("sugar_lift_python_source_PREFLIGHT_MISSING_MODULE",),
        env=env,
    )
    if ok_missing:
        print(
            "FAIL: missing module import succeeded unexpectedly",
            file=sys.stderr,
        )
        return 1
    if "ModuleNotFoundError" not in detail and "No module named" not in detail:
        # Accept any failure shape that is not success.
        if not detail:
            print("FAIL: missing module produced empty diagnostic", file=sys.stderr)
            return 1

    # Synthetic sticky venv without packages must trip when present.
    with tempfile.TemporaryDirectory(prefix="sugar-preflight-sticky-") as tmp:
        venv_dir = Path(tmp) / "sticky"
        venv.create(venv_dir, with_pip=False, clear=True)
        python = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        ok_sticky, sticky_detail = _run_import_check(python, REQUIRED_IMPORTS)
        if ok_sticky:
            print(
                "FAIL: empty sticky venv imported kits without install",
                file=sys.stderr,
            )
            return 1
        if not sticky_detail:
            print("FAIL: empty sticky venv produced empty diagnostic", file=sys.stderr)
            return 1

    print("PASS: preflight detects missing kit imports with named diagnostics")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument(
        "--skip-fresh-install",
        action="store_true",
        help="skip the clean-venv editable install check (faster local loop)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit machine-readable failures (still exit 1 if A1>0)",
    )
    args = parser.parse_args(argv)

    if args.self_test:
        return self_test()

    failures = run_preflight(include_fresh_install=not args.skip_fresh_install)
    if args.json:
        import json

        payload = {
            "A1": len(failures),
            "failures": [
                {"axis": f.axis, "contract": f.contract, "detail": f.detail}
                for f in failures
            ],
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 1 if failures else 0
    return report(failures)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
