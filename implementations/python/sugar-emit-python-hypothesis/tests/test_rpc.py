"""RPC dispatch conventions for the Hypothesis emitter."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from sugar_emit_python_hypothesis.rpc import dispatch


def _op(name: str, *args: dict) -> dict:
    return {"kind": "op", "name": name, "args": list(args)}


def _var(name: str) -> dict:
    return {"kind": "var", "name": name}


def test_describe_returns_emit_plugin_memento_for_hypothesis() -> None:
    response = dispatch({"jsonrpc": "2.0", "id": 1, "method": "sugar.plugin.describe"})
    result = response["result"]

    assert response["id"] == 1
    assert set(result.keys()) == {"envelope", "header", "metadata"}
    header = result["header"]
    assert header["kind"] == "emit"
    assert "pep/1.7.0" in header["protocol_versions"]
    assert header["content"]["target_language"] == "python"
    assert header["content"]["target_framework"] == "hypothesis"
    assert "concept:lt" in header["content"]["capabilities"]["predicates"]
    json.dumps(response)


def test_kit_declaration_returns_emit_only_hypothesis_declaration() -> None:
    response = dispatch(
        {"jsonrpc": "2.0", "id": 11, "method": "sugar.plugin.kit_declaration"}
    )
    result = response["result"]

    assert response["id"] == 11
    assert result["kit"] == {
        "id": "python-hypothesis",
        "language": "python",
        "version": "0.1.0",
    }
    method_names = {method["name"] for method in result["rpc"]["methods"]}
    assert method_names == {
        "initialize",
        "sugar.plugin.describe",
        "sugar.plugin.invoke",
        "sugar.plugin.check",
        "sugar.plugin.shutdown",
        "sugar.plugin.kit_declaration",
        "shutdown",
    }
    assert result["proofResolution"] == {"strategy": "pip"}
    assert result["effectKinds"] == []
    assert result["effectLeaves"] == []
    assert result["guardPredicates"] == []
    assert result["controlCarriers"] == []
    assert result["residueCategories"] == []
    json.dumps(response)


def test_kit_declaration_stdio_round_trip() -> None:
    src = Path(__file__).resolve().parents[1] / "src"
    env = os.environ.copy()
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(src) if not existing else os.pathsep.join([str(src), existing])
    )
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize"},
        {"jsonrpc": "2.0", "id": 2, "method": "sugar.plugin.kit_declaration"},
        {"jsonrpc": "2.0", "id": 3, "method": "shutdown"},
    ]
    completed = subprocess.run(
        [sys.executable, "-m", "sugar_emit_python_hypothesis", "--rpc"],
        input="\n".join(json.dumps(message) for message in messages) + "\n",
        text=True,
        capture_output=True,
        env=env,
        timeout=10,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    responses = [
        json.loads(line) for line in completed.stdout.splitlines() if line.strip()
    ]
    initialize = next(response for response in responses if response.get("id") == 1)
    declaration = next(response for response in responses if response.get("id") == 2)
    assert initialize["result"]["name"] == "python-hypothesis"
    assert declaration["result"]["kit"]["id"] == "python-hypothesis"
    assert declaration["result"]["effectKinds"] == []


def test_invoke_emits_hypothesis_module() -> None:
    response = dispatch(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "sugar.plugin.invoke",
            "params": {
                "contract_id": "concept:lt",
                "function": "ordered",
                "params": ["x", "y"],
                "param_types": ["int", "int"],
                "predicates": [_op("concept:lt", _var("x"), _var("y"))],
            },
        }
    )

    result = response["result"]
    assert response["id"] == 2
    assert result["kind"] == "hypothesis-test-emission"
    assert result["path"] == "test_ordered_hypothesis_contract.py"
    assert result["extension"] == "py"
    assert "@given(data=st.data())" in result["source"]
    assert result["emitted_predicates"] == ["lt"]
    assert result["is_complete"] is True
    assert result["emitted_artifact_cid"].startswith("blake3-512:")
    json.dumps(response)


def test_invoke_reports_unsupported_gap() -> None:
    response = dispatch(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "sugar.plugin.invoke",
            "params": {
                "function": "f",
                "predicates": [_op("concept:fallible-err", _var("f"))],
            },
        }
    )

    result = response["result"]
    assert result["unsupported_predicates"] == ["fallible-err"]
    assert result["is_complete"] is False


def test_shutdown_returns_null_result() -> None:
    response = dispatch({"jsonrpc": "2.0", "id": 4, "method": "sugar.plugin.shutdown"})
    assert response == {"jsonrpc": "2.0", "id": 4, "result": None}


def test_invalid_params_error() -> None:
    response = dispatch(
        {"jsonrpc": "2.0", "id": 5, "method": "sugar.plugin.invoke", "params": []}
    )
    assert response["error"]["code"] == -32602
