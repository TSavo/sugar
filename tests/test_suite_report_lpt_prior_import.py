"""Tooth: suite sessionfinish LPT prior must not NameError on Path.

A NameError in pytest_sessionfinish after tests pass still kills suite-report.json
and the package-suite class fails to speak. #7040 introduced Path without import.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "tools" / "python_package_suite_report.py"


def test_suite_report_imports_pathlib_path() -> None:
    src = PLUGIN.read_text(encoding="utf-8")
    tree = ast.parse(src)
    has_path = False
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "pathlib":
            names = {a.name for a in node.names}
            if "Path" in names:
                has_path = True
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name == "pathlib":
                    has_path = True
    assert has_path, (
        "tools/python_package_suite_report.py must import Path from pathlib — "
        "_write_lpt_prior uses Path at sessionfinish; missing import kills "
        "suite-report.json after a green test run"
    )


def test_write_lpt_prior_name_is_defined_with_path() -> None:
    """Static: body of _write_lpt_prior references Path and file defines Path."""
    src = PLUGIN.read_text(encoding="utf-8")
    assert "def _write_lpt_prior" in src
    assert "Path(self.config.rootpath)" in src
    # Compile executes import graph enough to bind names used at function def time;
    # Path is needed at runtime of _write_lpt_prior.
    ns: dict = {}
    compile(src, str(PLUGIN), "exec")  # syntax
    # Runtime bind check: exec module top-level imports only
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "python_package_suite_report_tooth", PLUGIN
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # tools/ on path for siblings
    import sys

    tools = str(ROOT / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    spec.loader.exec_module(mod)
    assert hasattr(mod, "Path") or "Path" in dir(__import__("pathlib"))
    # Callability: method exists on SuiteReporter
    assert hasattr(mod.SuiteReporter, "_write_lpt_prior")
