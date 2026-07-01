"""Canonical op CID derivation shared by Python lifters.

An operation CID is the canonical JSON CID of the operation shape. The shape
defines the operation; caller-facing names remain sugar around that preimage.
"""

from __future__ import annotations

from typing import Any

from .canonicalizer import (
    Value,
    blake3_512_of,
    encode_jcs,
    varr,
    vbool,
    vint,
    vnull,
    vobj,
    vstr,
)

Json = Any
LEGACY_CONCEPT_PREFIX = "concept:"


def op_cid_from_shape(shape: Json) -> str:
    return blake3_512_of(encode_jcs(_json_to_value(shape)).encode("utf-8"))


def bare_local_operator_name(name: str) -> str:
    return name.removeprefix(LEGACY_CONCEPT_PREFIX)


def local_operator_shape(name: str) -> dict[str, Json]:
    return {"kind": "local-operator", "name": bare_local_operator_name(name)}


def local_op_cid(name: str) -> str:
    return op_cid_from_shape(local_operator_shape(name))


def _json_to_value(value: Json) -> Value:
    if value is None:
        return vnull()
    if isinstance(value, bool):
        return vbool(value)
    if isinstance(value, int):
        return vint(value)
    if isinstance(value, str):
        return vstr(value)
    if isinstance(value, list):
        return varr([_json_to_value(item) for item in value])
    if isinstance(value, dict):
        pairs: list[tuple[str, Value]] = []
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("canonical JSON object keys must be str")
            pairs.append((key, _json_to_value(item)))
        return vobj(pairs)
    raise TypeError(f"unsupported canonical JSON value: {type(value).__name__}")
