"""Stage an installed Python package as a lift workspace.

What remains of the deleted numpy/pandas panic audit: resolving an installed
import to its source path, and staging that source with a Python kit manifest
so ``sugar mint`` can read it. The construction frontier over an installed
package is the board door (``scripts/control_effect_recensus.py``); nothing
here measures it (#7806).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def _resolve_installed_package_path(package: str) -> Path:
    """Resolve an installed import to a lift target path.

    Package modules (``numpy/__init__.py``) resolve to the package directory.
    Single-module libraries (stdlib ``statistics.py``) resolve to the module
    *file* — using the parent directory would stage the entire stdlib tree.

    ``decimal`` is special: the public ``decimal`` import is a thin reexport that
    prefers the C accelerator ``_decimal`` when present. Staging
    ``decimal.__file__`` alone would stage only the try/import shim. Resolve to
    the pure-python implementation module ``_pydecimal`` (source file), never
    the C extension.
    """
    resolve_name = package
    if package == "decimal":
        # Public name stays "decimal" for axes/targets; body is _pydecimal.
        resolve_name = "_pydecimal"
    code = (
        "import importlib, os\n"
        f"mod = importlib.import_module({resolve_name!r})\n"
        "path = getattr(mod, '__file__', None)\n"
        "if path is None:\n"
        "    raise SystemExit('package has no __file__')\n"
        "path = os.path.abspath(path)\n"
        "base = os.path.basename(path)\n"
        "if base.endswith(('.so', '.pyd', '.dll')) or 'lib-dynload' in path:\n"
        "    raise SystemExit('C-extension path gap: ' + path)\n"
        "if base == '__init__.py':\n"
        "    print(os.path.dirname(path))\n"
        "else:\n"
        "    # Single-module file target (e.g. statistics.py / _pydecimal.py).\n"
        "    print(path)\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(detail or f"import {package} failed")
    return Path(completed.stdout.strip())


def _prepare_audit_workspace(target: Path, root: Path, audit_workspace: Path) -> None:
    target = target.resolve()
    root = root.resolve()
    audit_workspace.mkdir(parents=True, exist_ok=True)
    if target.is_file():
        # Single-module library (e.g. stdlib statistics.py): stage the file
        # itself. Path.rglob on a file is empty — never silent-empty-workspace.
        if target.suffix != ".py":
            raise ValueError(f"audit target file must be a .py module, got {target}")
        destination = audit_workspace / target.name
        shutil.copy2(target, destination)
    else:
        for source in sorted(target.rglob("*.py")):
            if "__pycache__" in source.parts:
                continue
            relative = source.relative_to(target)
            destination = audit_workspace / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

    sugar_dir = audit_workspace / ".sugar"
    manifest_dir = sugar_dir / "lift/python"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (sugar_dir / "config.toml").write_text(_audit_config_toml(), encoding="utf-8")
    (manifest_dir / "manifest.toml").write_text(
        _audit_manifest_toml(root),
        encoding="utf-8",
    )


def _audit_config_toml() -> str:
    return "\n".join(
        [
            "[[plugins]]",
            'name = "python-audit-lift"',
            'kind = "lift"',
            'surface = "python"',
            'emit = "ir-document"',
            "",
        ]
    )


def _audit_manifest_toml(root: Path) -> str:
    lift_rpc = (
        root
        / "implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/lift_rpc.py"
    )
    command = [
        sys.executable,
        str(lift_rpc),
        "--rpc",
    ]
    command_items = ", ".join(_toml_string(item) for item in command)
    return "\n".join(
        [
            'name = "python-audit-lift"',
            'version = "0.1.0"',
            'protocol_version = "pep/1.7.0"',
            'kind = "lift"',
            f"command = [{command_items}]",
            f"working_dir = {_toml_string(str(root))}",
            "",
            "[capabilities]",
            'authoring_surfaces = ["python"]',
            'ir_version = "v1.1.0"',
            "emits_signed_mementos = false",
            "",
        ]
    )


def _toml_string(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
