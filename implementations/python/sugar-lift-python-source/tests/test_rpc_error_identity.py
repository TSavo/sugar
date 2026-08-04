"""JSON-RPC failures retain the identity of the decoded request."""

from __future__ import annotations

import io
import json
from types import ModuleType

import pytest

from sugar_lift_python_source import bind_rpc, rpc, verify_rpc
from sugar_source_tree.binding_state import ConstructedValueCategoryGap


class _CapturedStdout:
    def __init__(self) -> None:
        self.buffer = io.BytesIO()

    def write(self, value: str) -> int:
        return self.buffer.write(value.encode("utf-8"))

    def flush(self) -> None:
        return None

    def response(self) -> dict[str, object]:
        return json.loads(self.buffer.getvalue())


RPC_MODULES = (rpc, bind_rpc, verify_rpc)


def _run_one(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch, request: str
) -> dict[str, object]:
    stdout = _CapturedStdout()
    monkeypatch.setattr(module.sys, "stdin", io.StringIO(request + "\n"))
    monkeypatch.setattr(module.sys, "stdout", stdout)
    module.run_rpc()
    return stdout.response()


@pytest.mark.parametrize("module", RPC_MODULES)
def test_decoded_request_exception_keeps_id_and_named_reason(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(_request: dict[str, object]) -> dict[str, object]:
        raise ConstructedValueCategoryGap(
            "unclassified constructed value category builtins.complex"
        )

    monkeypatch.setattr(module, "dispatch", refuse)

    response = _run_one(
        module,
        monkeypatch,
        '{"jsonrpc":"2.0","id":37,"method":"sugar.enumerate","params":{}}',
    )

    assert response["id"] == 37
    assert response["error"]["code"] == -32603  # type: ignore[index]
    assert response["error"]["data"] == {  # type: ignore[index]
        "exception_type": "ConstructedValueCategoryGap",
        "stage": "dispatch",
    }
    assert str(response["error"]["message"]).startswith(  # type: ignore[index]
        "ConstructedValueCategoryGap: unclassified constructed value category "
        "builtins.complex"
    )


@pytest.mark.parametrize("module", RPC_MODULES)
def test_normal_request_keeps_existing_result_shape(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    response = _run_one(
        module,
        monkeypatch,
        '{"jsonrpc":"2.0","id":41,"method":"shutdown","params":{}}',
    )

    assert response["id"] == 41
    assert "result" in response
    assert "error" not in response


@pytest.mark.parametrize("module", RPC_MODULES)
def test_undecoded_parse_error_remains_unattributed(
    module: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    response = _run_one(module, monkeypatch, "{")

    assert response["id"] is None
    assert response["error"]["code"] == -32700  # type: ignore[index]
