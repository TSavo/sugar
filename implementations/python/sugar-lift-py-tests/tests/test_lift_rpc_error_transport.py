from __future__ import annotations

import threading
from typing import Any

import pytest

from sugar_lift_py_tests.gap.panic import construction_panic_gap
from sugar_lift_py_tests import lift_rpc


def test_rpc_dispatch_returns_construction_panic_as_json_rpc_error(monkeypatch) -> None:
    """ConstructionPanic: error frame then process death — never soft success."""
    messages: list[dict[str, Any]] = [
        {"jsonrpc": "2.0", "id": 2, "method": "lift", "params": {}},
        {"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": {}},
    ]
    sent: list[dict[str, Any]] = []

    def _recv():
        return messages.pop(0) if messages else None

    monkeypatch.setattr(lift_rpc, "_configure_transport_logging", lambda: None)
    monkeypatch.setattr(lift_rpc, "_recv", _recv)
    monkeypatch.setattr(lift_rpc, "_send", sent.append)

    def panic_dispatch(msg: dict[str, Any]) -> bool:
        if msg.get("method") == "shutdown":
            return False
        construction_panic_gap(
            owner="rpc-fixture",
            blame="fixture.py:1:0",
            observed="missing",
            requested="value",
            fix="return a JSON-RPC error frame",
        )
        return True

    monkeypatch.setattr(lift_rpc, "_dispatch_request", panic_dispatch)

    with pytest.raises(SystemExit) as halted:
        lift_rpc.main(["--rpc"])

    assert halted.value.code == 1
    # Shutdown never runs — process dies on ConstructionPanic.
    assert messages == [{"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": {}}]
    assert len(sent) == 1
    assert sent[0]["id"] == 2
    assert sent[0]["error"]["code"] == -32603
    assert sent[0]["error"]["data"]["exception_type"] == "ConstructionPanic"
    assert sent[0]["error"]["data"]["diagnostic"]["owner"] == "rpc-fixture"
    assert "result" not in sent[0]


def test_rpc_dispatch_returns_recursion_error_as_json_rpc_error(monkeypatch) -> None:
    """C-stack-safe overflow: RecursionError must produce a typed frame and
    leave the transport alive for the next request — never a dead process."""
    messages: list[dict[str, Any]] = [
        {"jsonrpc": "2.0", "id": 7, "method": "lift", "params": {}},
        {"jsonrpc": "2.0", "id": 8, "method": "shutdown", "params": {}},
    ]
    sent: list[dict[str, Any]] = []

    def _recv():
        return messages.pop(0) if messages else None

    monkeypatch.setattr(lift_rpc, "_configure_transport_logging", lambda: None)
    monkeypatch.setattr(lift_rpc, "_recv", _recv)
    monkeypatch.setattr(lift_rpc, "_send", sent.append)

    def overflow_dispatch(msg: dict[str, Any]) -> bool:
        if msg.get("method") == "shutdown":
            lift_rpc._send(
                {"jsonrpc": "2.0", "id": msg.get("id"), "result": {"ok": True}}
            )
            return False
        raise RecursionError("maximum recursion depth exceeded")

    monkeypatch.setattr(lift_rpc, "_dispatch_request", overflow_dispatch)

    lift_rpc.main(["--rpc"])

    assert messages == []
    assert len(sent) == 2
    assert sent[0]["id"] == 7
    assert sent[0]["error"]["code"] == -32603
    assert sent[0]["error"]["data"]["exception_type"] == "RecursionError"
    assert "recursion limit exceeded" in sent[0]["error"]["message"]
    assert sent[1] == {"jsonrpc": "2.0", "id": 8, "result": {"ok": True}}


def test_rpc_serves_on_main_thread_without_a_big_stack_shell(monkeypatch) -> None:
    """Iterative block follow retires the oversized worker-stack workaround."""
    messages = [{"jsonrpc": "2.0", "id": 8, "method": "shutdown", "params": {}}]
    sent: list[dict[str, Any]] = []

    monkeypatch.setattr(lift_rpc, "_configure_transport_logging", lambda: None)
    monkeypatch.setattr(lift_rpc, "_recv", lambda: messages.pop(0))
    monkeypatch.setattr(lift_rpc, "_send", sent.append)

    def worker_thread_is_retired(*args, **kwargs):
        del args, kwargs
        raise AssertionError(
            "RPC must not hide native recursion on a huge worker stack"
        )

    monkeypatch.setattr(threading, "Thread", worker_thread_is_retired)

    lift_rpc.main(["--rpc"])

    assert sent == [{"jsonrpc": "2.0", "id": 8, "result": {"ok": True}}]


def test_enumeration_phase_profile_orders_dominant_cost_first(monkeypatch) -> None:
    monkeypatch.setattr(lift_rpc, "_ENUMERATION_PHASES", {})

    lift_rpc._observe_enumeration_phase("response.encode", 2.0)
    lift_rpc._observe_enumeration_phase("file_context.lift", 10.0)
    lift_rpc._observe_enumeration_phase("file_context.lift", 20.0)

    assert lift_rpc._enumeration_phase_snapshot() == [
        {
            "phase": "file_context.lift",
            "phase_count": 2,
            "phase_total_ms": 30.0,
            "phase_mean_ms": 15.0,
            "phase_max_ms": 20.0,
        },
        {
            "phase": "response.encode",
            "phase_count": 1,
            "phase_total_ms": 2.0,
            "phase_mean_ms": 2.0,
            "phase_max_ms": 2.0,
        },
    ]
