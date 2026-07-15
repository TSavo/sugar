from __future__ import annotations

from typing import Any

import pytest

from sugar_lift_py_tests.factory import factory_panic_gap
from sugar_lift_py_tests import lift_rpc


def test_rpc_dispatch_returns_factory_panic_as_json_rpc_error(monkeypatch) -> None:
    """A semantic lift failure must produce a frame, never transport EOF."""
    messages: list[dict[str, Any]] = [
        {"jsonrpc": "2.0", "id": 2, "method": "lift", "params": {}},
        {"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": {}},
    ]
    sent: list[dict[str, Any]] = []

    monkeypatch.setattr(lift_rpc, "_configure_transport_logging", lambda: None)
    monkeypatch.setattr(lift_rpc, "_recv", lambda: messages.pop(0))
    monkeypatch.setattr(lift_rpc, "_send", sent.append)

    def panic_lift(msg_id: Any, params: dict[str, Any]) -> None:
        del msg_id, params
        factory_panic_gap(
            owner="rpc-fixture",
            blame="fixture.py:1:0",
            observed="missing",
            requested="value",
            fix="return a JSON-RPC error frame",
        )

    monkeypatch.setattr(lift_rpc, "_handle_lift", panic_lift)

    with pytest.raises(SystemExit) as halted:
        lift_rpc.main(["--rpc"])

    assert halted.value.code == 1
    assert messages == [{"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": {}}]
    assert sent == [
        {
            "jsonrpc": "2.0",
            "id": 2,
            "error": {
                "code": -32603,
                "message": (
                    "FACTORY PANIC: match(Sugar) { Some => cite_or_effect, "
                    "None => panic!() }\nwrite more Floor for this Construction: "
                    "owner=rpc-fixture blame=fixture.py:1:0 observed=missing "
                    "requested=value fix=return a JSON-RPC error frame"
                ),
                "data": {
                    "exception_type": "FactoryPanic",
                    "stage": "dispatch",
                    "diagnostic": {
                        "owner": "rpc-fixture",
                        "blame": "fixture.py:1:0",
                        "observed": "missing",
                        "requested": "value",
                        "fix": "return a JSON-RPC error frame",
                        "gap_kind": "Floor",
                        "gap_locus": "Construction",
                    },
                },
            },
        },
    ]
    assert "result" not in sent[0]


def test_rpc_dispatch_returns_recursion_error_as_json_rpc_error(monkeypatch) -> None:
    """C-stack-safe overflow: RecursionError must produce a typed frame and
    leave the transport alive for the next request — never a dead process."""
    messages: list[dict[str, Any]] = [
        {"jsonrpc": "2.0", "id": 7, "method": "lift", "params": {}},
        {"jsonrpc": "2.0", "id": 8, "method": "shutdown", "params": {}},
    ]
    sent: list[dict[str, Any]] = []

    monkeypatch.setattr(lift_rpc, "_configure_transport_logging", lambda: None)
    monkeypatch.setattr(lift_rpc, "_recv", lambda: messages.pop(0))
    monkeypatch.setattr(lift_rpc, "_send", sent.append)

    def overflow_lift(msg_id: Any, params: dict[str, Any]) -> None:
        del msg_id, params
        raise RecursionError("maximum recursion depth exceeded")

    monkeypatch.setattr(lift_rpc, "_handle_lift", overflow_lift)

    lift_rpc.main(["--rpc"])

    assert messages == []
    assert sent[0]["id"] == 7
    assert sent[0]["error"]["code"] == -32603
    assert sent[0]["error"]["data"]["exception_type"] == "RecursionError"
    assert "recursion limit exceeded" in sent[0]["error"]["message"]


def test_rpc_serve_thread_uses_explicit_stack_and_recursion_limit() -> None:
    """The serve loop runs on a worker thread with a large explicit C stack so
    depth is bounded by the explicit recursion limit, not the OS stack."""
    assert lift_rpc._SERVE_THREAD_STACK_BYTES == 512 * 1024 * 1024
    assert lift_rpc._SERVE_RECURSION_LIMIT == 100_000
