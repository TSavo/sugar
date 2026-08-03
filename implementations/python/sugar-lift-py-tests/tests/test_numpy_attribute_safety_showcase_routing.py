# SPDX-License-Identifier: MIT OR Apache-2.0
"""The NumPy attribute-safety showcase routes full construction to its owner."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
PY_TESTS_SRC = ROOT / "implementations/python/sugar-lift-py-tests/src"
PY_SOURCE_SRC = ROOT / "implementations/python/sugar-lift-python-source/src"
SOURCE_TREE_SRC = ROOT / "implementations/python/sugar-source-tree/src"
for source_root in (PY_TESTS_SRC, PY_SOURCE_SRC, SOURCE_TREE_SRC):
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

from sugar_lift_py_tests import lift_rpc  # noqa: E402

SHOWCASE = ROOT / "examples/numpy-attribute-safety-showcase"
PARAMETER_LINK_UNITS = "parameter-contract-link-units"


def _python_source_response(request: dict) -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(PY_SOURCE_SRC), env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    code = """
import json
import sys
from sugar_lift_python_source import rpc

print(json.dumps(rpc.dispatch(json.loads(sys.argv[1]))))
"""
    completed = subprocess.run(
        [sys.executable, "-c", code, json.dumps(request)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def _selected_full_fold_module(suite: str) -> tuple[str, Path]:
    suite_root = SHOWCASE / suite
    config = tomllib.loads(
        (suite_root / ".sugar/config.toml").read_text(encoding="utf-8")
    )
    plugin = next(
        plugin
        for plugin in config["plugins"]
        if plugin.get("emit") == "ir-document"
    )
    manifest_path = (
        suite_root
        / ".sugar/lift"
        / plugin["surface"]
        / "manifest.toml.in"
    )
    manifest_text = (
        manifest_path.read_text(encoding="utf-8")
        .replace("@PYTHON@", sys.executable)
        .replace("@SUITE_SRC@", str(suite_root / "src"))
    )
    command = tomllib.loads(manifest_text)["command"]
    module_flag = command.index("-m")
    return command[module_flag + 1], suite_root / "src"


def _enumerate_from_module(module: str, workspace_root: Path) -> dict:
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "sugar.enumerate",
        "params": {
            "level": PARAMETER_LINK_UNITS,
            "workspace_root": str(workspace_root),
            "options": {},
        },
    }
    if module == "sugar_lift_python_source":
        return _python_source_response(request)
    if module == "sugar_lift_py_tests.lift_rpc":
        captured = []
        original_send = lift_rpc._send
        lift_rpc._send = captured.append
        try:
            lift_rpc._dispatch_request(request)
        finally:
            lift_rpc._send = original_send
        assert len(captured) == 1, captured
        return captured[0]
    pytest.fail(f"showcase selected an unauthenticated full-fold module: {module}")


@pytest.mark.parametrize("suite", ["good", "bad"])
def test_showcase_routes_full_fold_to_parameter_enumeration_owner(
    suite: str, tmp_path: Path
) -> None:
    module, _showcase_source_root = _selected_full_fold_module(suite)
    (tmp_path / "identity.py").write_text(
        "def identity(value):\n    return value\n", encoding="utf-8"
    )

    response = _enumerate_from_module(module, tmp_path)

    assert "error" not in response, response
    assert isinstance(response["result"]["rows"], list), response


def test_python_source_keeps_its_parameter_enumeration_membrane() -> None:
    response = _python_source_response(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "sugar.enumerate",
            "params": {
                "level": PARAMETER_LINK_UNITS,
                "workspace_root": str(SHOWCASE / "good/src"),
                "options": {},
            },
        }
    )

    assert response["error"]["code"] == -32602
    assert "not served by surface `python-source`" in response["error"]["message"]
