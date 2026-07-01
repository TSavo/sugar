from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import blake3 as _blake3

BLAKE3_512_PREFIX = "blake3-512:"


@dataclass(frozen=True)
class _Null:
    pass


@dataclass(frozen=True)
class _Bool:
    value: bool


@dataclass(frozen=True)
class _Int:
    value: int


@dataclass(frozen=True)
class _Str:
    value: str


@dataclass(frozen=True)
class _Arr:
    items: tuple["Value", ...]


@dataclass(frozen=True)
class _Obj:
    entries: tuple[tuple[str, "Value"], ...]


Value = _Null | _Bool | _Int | _Str | _Arr | _Obj


def vnull() -> Value:
    return _Null()


def vbool(value: bool) -> Value:
    return _Bool(bool(value))


def vint(value: int) -> Value:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError("vint requires int")
    return _Int(int(value))


def vstr(value: str) -> Value:
    if not isinstance(value, str):
        raise TypeError("vstr requires str")
    return _Str(value)


def varr(items: list[Value]) -> Value:
    return _Arr(tuple(items))


def vobj(pairs: list[tuple[str, Value]]) -> Value:
    out: list[tuple[str, Value]] = []
    for key, value in pairs:
        if not isinstance(key, str):
            raise TypeError("vobj keys must be str")
        out.append((key, value))
    return _Obj(tuple(out))


def encode_jcs(value: Value) -> str:
    out: list[str] = []
    _encode(value, out)
    return "".join(out)


def _encode(value: Value, out: list[str]) -> None:
    if isinstance(value, _Null):
        out.append("null")
    elif isinstance(value, _Bool):
        out.append("true" if value.value else "false")
    elif isinstance(value, _Int):
        out.append(str(value.value))
    elif isinstance(value, _Str):
        _encode_string(value.value, out)
    elif isinstance(value, _Arr):
        out.append("[")
        for index, item in enumerate(value.items):
            if index > 0:
                out.append(",")
            _encode(item, out)
        out.append("]")
    elif isinstance(value, _Obj):
        out.append("{")
        for index, (key, item) in enumerate(
            sorted(value.entries, key=lambda kv: kv[0])
        ):
            if index > 0:
                out.append(",")
            _encode_string(key, out)
            out.append(":")
            _encode(item, out)
        out.append("}")
    else:
        raise TypeError(f"unknown Value variant: {type(value)!r}")


def _encode_string(value: str, out: list[str]) -> None:
    out.append('"')
    for char in value:
        codepoint = ord(char)
        if char == '"':
            out.append('\\"')
        elif char == "\\":
            out.append("\\\\")
        elif codepoint < 0x20:
            out.append("\\u00")
            out.append("0123456789abcdef"[(codepoint >> 4) & 0xF])
            out.append("0123456789abcdef"[codepoint & 0xF])
        else:
            out.append(char)
    out.append('"')


def blake3_512_of(data: bytes) -> str:
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("blake3_512_of requires bytes")
    digest = _blake3.blake3(bytes(data)).digest(length=64)
    return BLAKE3_512_PREFIX + digest.hex()


def canonical_json_bytes(value: Any) -> bytes:
    return encode_jcs(_json_to_value(value)).encode("utf-8")


def cid_of_json(value: Any) -> str:
    return blake3_512_of(canonical_json_bytes(value))


def template_json_bytes(value: Any) -> bytes:
    """Compact serde_json::Value::to_string style bytes for recognize templates."""
    return json.dumps(value, separators=(",", ":"), sort_keys=False).encode("utf-8")


def template_cid_of_json(value: Any) -> str:
    return blake3_512_of(template_json_bytes(value))


def _json_to_value(value: Any) -> Value:
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
