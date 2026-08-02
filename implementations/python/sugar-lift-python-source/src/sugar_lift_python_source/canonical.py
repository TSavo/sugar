from __future__ import annotations

import json
import re as _re
from dataclasses import dataclass
from typing import Any, NoReturn

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


def _could_not_encode(
    *,
    owner: str,
    observed: str,
    requested: str,
    fix: str,
) -> NoReturn:
    """Wire-codec refusal: name what the canonicalizer could not build.

    Bare TypeError(type(...)) at this door dumps a class name and hides
    whether the payload was malformed or the encoder arm was never written.
    """
    from sugar_lift_py_tests.gap.panic import construction_panic_gap

    construction_panic_gap(
        owner=owner,
        blame="canonical",
        observed=observed,
        requested=requested,
        fix=fix,
    )


def vnull() -> Value:
    return _Null()


def vbool(value: bool) -> Value:
    return _Bool(bool(value))


def vint(value: int) -> Value:
    if not isinstance(value, int) or isinstance(value, bool):
        _could_not_encode(
            owner="canonical.vint",
            observed=f"vint received {type(value).__name__}",
            requested="int (not bool)",
            fix="pass a plain int into vint; bool is not an int wire value",
        )
    return _Int(int(value))


def vstr(value: str) -> Value:
    if not isinstance(value, str):
        _could_not_encode(
            owner="canonical.vstr",
            observed=f"vstr received {type(value).__name__}",
            requested="str",
            fix="pass a str into vstr",
        )
    return _Str(value)


def varr(items: list[Value]) -> Value:
    return _Arr(tuple(items))


def vobj(pairs: list[tuple[str, Value]]) -> Value:
    out: list[tuple[str, Value]] = []
    for key, value in pairs:
        if not isinstance(key, str):
            _could_not_encode(
                owner="canonical.vobj",
                observed=f"vobj key is {type(key).__name__}",
                requested="str keys",
                fix="use string keys in vobj pairs",
            )
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
        _could_not_encode(
            owner="canonical.encode",
            observed=f"unknown Value variant: {type(value).__name__}",
            requested="_Null | _Bool | _Int | _Str | _Arr | _Obj",
            fix=f"write encode arm for {type(value).__name__} or construct via vint/vstr/vobj",
        )


# The JCS string escape set for this canonicalizer: only `"`, `\`, and the C0
# controls (as lowercase `\u00XX`) are escaped. `/` is NOT escaped, non-ASCII is
# emitted raw (including astral characters and lone surrogates, whose encoding
# error surfaces later at `.encode("utf-8")`).
_ESCAPE_SEARCH = _re.compile(r'["\\\x00-\x1f]').search

_ESCAPE_TABLE: dict[int, str] = {
    0x22: '\\"',
    0x5C: "\\\\",
    **{
        codepoint: "\\u00"
        + "0123456789abcdef"[codepoint >> 4]
        + "0123456789abcdef"[codepoint & 0xF]
        for codepoint in range(0x20)
    },
}


def _encode_string(value: str, out: list[str]) -> None:
    # Fast path: nothing to escape (the overwhelming majority of corpus strings
    # are identifiers and CIDs). Byte-identical to the per-character loop.
    if _ESCAPE_SEARCH(value) is None:
        out.append('"' + value + '"')
        return
    out.append('"' + value.translate(_ESCAPE_TABLE) + '"')


def blake3_512_of(data: bytes) -> str:
    if not isinstance(data, (bytes, bytearray)):
        _could_not_encode(
            owner="canonical.blake3_512_of",
            observed=f"blake3_512_of received {type(data).__name__}",
            requested="bytes | bytearray",
            fix="hash bytes; encode strings first",
        )
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
                _could_not_encode(
                    owner="canonical.json_to_value",
                    observed=f"JSON object key is {type(key).__name__}",
                    requested="str keys",
                    fix="use string keys in JSON objects before canonicalization",
                )
            pairs.append((key, _json_to_value(item)))
        return vobj(pairs)
    _could_not_encode(
        owner="canonical.json_to_value",
        observed=f"unsupported canonical JSON value: {type(value).__name__}",
        requested="None | bool | int | str | list | dict",
        fix=f"write _json_to_value arm for {type(value).__name__} or convert before cid_of_json",
    )
