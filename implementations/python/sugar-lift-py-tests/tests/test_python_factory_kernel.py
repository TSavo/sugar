from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from sugar_lift_py_tests.claim import SugarCatalog, SugarClaim, SugarRole
from sugar_lift_py_tests.factory import FactoryGap, build_next


ROOT = Path(__file__).resolve().parents[4]
PYTHON_KIT = ROOT / "implementations/python"
PY_TESTS = PYTHON_KIT / "sugar-lift-py-tests"


def test_python_lib_lift_source_delegates_to_factory_not_lsp(monkeypatch) -> None:
    from sugar_lift_py_tests import lib, lsp

    monkeypatch.setattr(
        lsp,
        "_lift_source",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("old entrypoint reused")),
    )

    with pytest.raises(FactoryGap) as raised:
        lib.lift_source("base64.py", "def encode_len(data):\n    return len(data)\n")

    assert raised.value.info == {
        "owner": "python.factory",
        "blame": "base64.py:2:15",
        "observed": "Name",
        "requested": "term",
        "fix": "create sugar_lift_py_tests.sugar.name.name_sugar",
    }


def test_batch_lift_entrypoints_use_lift_rpc_not_lsp() -> None:
    manifest = (PYTHON_KIT / ".sugar/lift/python/manifest.toml").read_text(encoding="utf-8")
    pyproject = (PY_TESTS / "pyproject.toml").read_text(encoding="utf-8")

    assert 'command = ["python3", "-m", "sugar_lift_py_tests.lift_rpc", "--rpc"]' in manifest
    assert 'sugar-lift-python = "sugar_lift_py_tests.lift_rpc:main"' in pyproject
    assert 'sugar-lift-python = "sugar_lift_py_tests.lsp:main"' not in pyproject


def test_lift_rpc_reports_factory_gap_without_old_lsp_entry(tmp_path) -> None:
    source = tmp_path / "base64.py"
    source.write_text("def encode_len(data):\n    return len(data)\n", encoding="utf-8")
    env = {
        **os.environ,
        "PYTHONPATH": str(PY_TESTS / "src"),
    }
    request = "\n".join(
        json.dumps(message)
        for message in [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "lift",
                "params": {"workspace_root": str(tmp_path), "source_paths": ["."]},
            },
            {"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": {}},
        ]
    )

    completed = subprocess.run(
        [sys.executable, "-m", "sugar_lift_py_tests.lift_rpc", "--rpc"],
        input=request + "\n",
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert completed.returncode == 0, completed.stderr
    responses = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
    lift_response = next(response for response in responses if response.get("id") == 2)
    assert lift_response["error"]["message"].startswith("write more Sugar for this AST")
    assert lift_response["error"]["data"]["info"] == {
        "owner": "python.factory",
        "blame": str(source) + ":2:15",
        "observed": "Name",
        "requested": "term",
        "fix": "create sugar_lift_py_tests.sugar.name.name_sugar",
    }


def test_factory_without_sugar_panics_on_last_popped_source_site() -> None:
    source = "def encode_len(data):\n    return len(data)\n"

    with pytest.raises(FactoryGap) as raised:
        build_next(source, filename="base64.py", role=SugarRole.TERM)

    gap = raised.value
    assert str(gap).startswith("write more Sugar for this AST")
    assert gap.info == {
        "owner": "python.factory",
        "blame": "base64.py:2:15",
        "observed": "Name",
        "requested": "term",
        "fix": "create sugar_lift_py_tests.sugar.name.name_sugar",
    }
    assert gap.audit_row.to_json() == {
        "kind": "factory-audit-row",
        "role": "term",
        "status": "sugar-gap",
        "observed": "Name",
        "blame": "base64.py:2:15",
        "selected": None,
        "candidates": [],
        "message": str(gap),
    }


def test_factory_matches_registered_sugar_for_last_popped_source_site() -> None:
    source = "def encode_len(data):\n    return len(data)\n"

    @dataclass(frozen=True)
    class NameSugar:
        identifier: str

    def owns_name(site) -> bool:
        return isinstance(site.node, ast.Name)

    def build_name(site) -> NameSugar:
        return NameSugar(site.node.id)

    catalog = SugarCatalog(
        [
            SugarClaim(
                name="python.name",
                role=SugarRole.TERM,
                owns=owns_name,
                build=build_name,
            )
        ]
    )

    result = build_next(source, filename="base64.py", role=SugarRole.TERM, catalog=catalog)

    assert result.sugar == NameSugar("data")
    assert result.audit_row.to_json() == {
        "kind": "factory-audit-row",
        "role": "term",
        "status": "selected",
        "observed": "Name",
        "blame": "base64.py:2:15",
        "selected": "python.name",
        "candidates": ["python.name"],
        "message": "selected Sugar `python.name` for role term at `base64.py:2:15`",
    }
