from __future__ import annotations

import json
import re as _re
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


# The JCS string escape set for this canonicalizer: `"`, `\`, the C0 controls
# (as lowercase `\u00XX`) and the lone surrogates (as lowercase `\udXXX`) are
# escaped. `/` is NOT escaped; every other code point, astral characters
# included, is emitted raw.
#
# A Python ``str`` can hold a surrogate code point (U+D800..U+DFFF) that no
# UTF-8 byte sequence spells: ``"\ud83d"`` in source is such a string. Every
# Python str is a value the lifter may construct, so every one has canonical
# bytes: the surrogate is written as its JSON code-point escape, which is
# ASCII. The encoding stays injective -- a literal backslash is itself escaped,
# so no other string writes the same text -- and every string without a
# surrogate is written exactly as before, so no existing CID moves.
_ESCAPE_SEARCH = _re.compile(r'["\\\x00-\x1f\ud800-\udfff]').search

_SURROGATE_SEARCH = _re.compile(r"[\ud800-\udfff]").search

_ESCAPE_TABLE: dict[int, str] = {
    0x22: '\\"',
    0x5C: "\\\\",
    **{
        codepoint: "\\u00"
        + "0123456789abcdef"[codepoint >> 4]
        + "0123456789abcdef"[codepoint & 0xF]
        for codepoint in range(0x20)
    },
    **{codepoint: f"\\u{codepoint:04x}" for codepoint in range(0xD800, 0xE000)},
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
        raise TypeError("blake3_512_of requires bytes")
    digest = _blake3.blake3(bytes(data)).digest(length=64)
    return BLAKE3_512_PREFIX + digest.hex()


# One pass for the documents that need no decision.
#
# ``encode_jcs(_json_to_value(value))`` is the specification: it allocates one
# frozen ``Value`` per JSON node and then walks that tree a second time. Every
# CID in the lifter is taken through it, so on one large file that was 1.1
# million allocations and 1.1 million encode calls for 55 thousand documents.
#
# The interpreter's own encoder writes the same bytes for the documents where
# the two cannot differ, and those are named exactly:
#
#   * every node is EXACTLY ``None``, ``bool``, ``int``, ``str``, ``list`` or
#     ``dict`` and every key is exactly ``str`` -- no subclass, no tuple, no
#     float, no coerced key. Anything else is not decided here: it goes to the
#     specification, which encodes it or refuses it as it always did;
#   * no string needed an escape. The two encoders escape the same characters
#     (``"``, ``\`` and the C0 controls) but spell five controls differently
#     (``\n`` against ``\u000a``). Every escape either one writes contains a
#     backslash and nothing else does, so text without a backslash holds no
#     escape, and both wrote every string raw. Text with one is encoded again
#     by the specification;
#   * no string holds a lone surrogate. The interpreter's encoder writes one
#     raw, which has no UTF-8 bytes; the specification escapes it. ASCII text
#     holds none (``str.isascii`` reads the string's kind, not its text), so
#     only non-ASCII text is searched.
_ONE_PASS_ENCODE = json.JSONEncoder(
    ensure_ascii=False,
    check_circular=False,
    sort_keys=True,
    separators=(",", ":"),
).encode


def _is_exact_document(value: Any) -> bool:
    """Whether every node of ``value`` is an exact JSON builtin."""
    kind = type(value)
    if kind is str or kind is int or kind is bool or value is None:
        return True
    if kind is list:
        for item in value:
            kind = type(item)
            if kind is str or kind is int or kind is bool or item is None:
                continue
            if not _is_exact_document(item):
                return False
        return True
    if kind is dict:
        for key, item in value.items():
            if type(key) is not str:
                return False
            kind = type(item)
            if kind is str or kind is int or kind is bool or item is None:
                continue
            if not _is_exact_document(item):
                return False
        return True
    return False


def canonical_json_bytes(value: Any) -> bytes:
    if _is_exact_document(value):
        text = _ONE_PASS_ENCODE(value)
        if "\\" not in text and (text.isascii() or _SURROGATE_SEARCH(text) is None):
            return text.encode("utf-8")
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
