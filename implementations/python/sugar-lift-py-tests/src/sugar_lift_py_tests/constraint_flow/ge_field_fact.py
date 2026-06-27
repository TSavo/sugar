from __future__ import annotations

from typing import Any


def ge_field_fact(owner: str, field: str, value: int) -> dict[str, Any]:
    return {
        "kind": "atomic",
        "name": ">=",
        "args": [
            {"kind": "field", "owner": owner, "name": field},
            {"kind": "int", "value": value},
        ],
    }
