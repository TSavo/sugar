"""RPC dispatch conventions for the unittest emitter."""

from __future__ import annotations

import io
import json

import pytest

from sugar_emit_python_unittest import rpc
from sugar_emit_python_unittest.rpc import dispatch


class _CapturedStdout:
    def __init__(self) -> None:
        self.buffer = io.BytesIO()

    def write(self, value: str) -> int:
        return self.buffer.write(value.encode("utf-8"))

    def flush(self) -> None:
        return None


def _run_one(monkeypatch: pytest.MonkeyPatch, request: str) -> dict[str, object]:
    stdout = _CapturedStdout()
    monkeypatch.setattr(rpc.sys, "stdin", io.StringIO(request + "\n"))
    monkeypatch.setattr(rpc.sys, "stdout", stdout)
    rpc.run_rpc()
    return json.loads(stdout.buffer.getvalue())


def test_dispatch_exception_keeps_request_id_and_named_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(_request: dict[str, object]) -> dict[str, object]:
        raise RuntimeError("planted emitter failure")

    monkeypatch.setattr(rpc, "dispatch", refuse)
    response = _run_one(
        monkeypatch,
        '{"jsonrpc":"2.0","id":37,"method":"sugar.plugin.invoke","params":{}}',
    )

    assert response["id"] == 37
    assert response["error"]["data"] == {  # type: ignore[index]
        "exception_type": "RuntimeError",
        "stage": "dispatch",
    }
    assert str(response["error"]["message"]).startswith(  # type: ignore[index]
        "RuntimeError: planted emitter failure"
    )


def test_run_rpc_normal_and_parse_error_controls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    normal = _run_one(
        monkeypatch,
        '{"jsonrpc":"2.0","id":41,"method":"sugar.plugin.shutdown","params":{}}',
    )
    assert normal == {"jsonrpc": "2.0", "id": 41, "result": None}

    malformed = _run_one(monkeypatch, "{")
    assert malformed["id"] is None
    assert malformed["error"]["code"] == -32700  # type: ignore[index]


def _atomic(name: str, *args: dict) -> dict:
    return {"kind": "atomic", "name": name, "args": list(args)}


def _var(name: str) -> dict:
    return {"kind": "var", "name": name}


def test_describe_returns_plugin_memento_shape() -> None:
    response = dispatch({"jsonrpc": "2.0", "id": 1, "method": "sugar.plugin.describe"})
    result = response["result"]
    header = result["header"]

    assert response["id"] == 1
    assert set(result.keys()) == {"envelope", "header", "metadata"}
    assert header["schemaVersion"] == "1"
    assert "pep/1.7.0" in header["protocol_versions"]
    assert header["content"]["target_language"] == "python"
    assert header["content"]["target_framework"] == "unittest"
    assert "concept:eq" in header["content"]["capabilities"]["predicates"]
    json.dumps(response)


def test_invoke_emits_unittest_module() -> None:
    response = dispatch(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "sugar.plugin.invoke",
            "params": {
                "contract_id": "concept:eq",
                "function": "f",
                "params": ["a", "b"],
                "param_types": ["int", "int"],
                "predicates": [_atomic("concept:eq", _var("a"), _var("b"))],
            },
        }
    )
    result = response["result"]

    assert response["id"] == 2
    assert result["kind"] == "unittest-test-emission"
    assert result["path"] == "test_f_contract.py"
    assert result["extension"] == "py"
    assert "class TestFContract(unittest.TestCase):" in result["source"]
    assert "self.assertEqual(a, b)" in result["source"]
    assert result["emitted_predicates"] == ["eq"]
    assert result["unsupported_predicates"] == []
    assert result["is_complete"] is True
    json.dumps(response)


def test_invoke_reports_unsupported_gap() -> None:
    response = dispatch(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "sugar.plugin.invoke",
            "params": {
                "function": "f",
                "predicates": [_atomic("concept:mystery", _var("a"))],
            },
        }
    )

    assert response["result"]["unsupported_predicates"] == ["mystery"]
    assert response["result"]["is_complete"] is False
