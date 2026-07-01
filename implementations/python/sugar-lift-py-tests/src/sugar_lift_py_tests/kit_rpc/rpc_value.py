from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol


class RpcDto(Protocol):
    def to_rpc(self) -> dict[str, Any]: ...


def to_rpc_value(value: Any) -> Any:
    if hasattr(value, "to_rpc"):
        return value.to_rpc()
    if isinstance(value, Mapping):
        return {str(key): to_rpc_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [to_rpc_value(item) for item in value]
    return value
