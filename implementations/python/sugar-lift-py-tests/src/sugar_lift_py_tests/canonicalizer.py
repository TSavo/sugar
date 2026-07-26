# SPDX-License-Identifier: MIT OR Apache-2.0
#
# Minimal Python port of sugar-canonicalizer.
#
# Mirrors implementations/rust/sugar-canonicalizer/src/{value,jcs,hash}.rs
# 1:1. Cross-language conformance is the load-bearing claim: the JCS bytes
# this module emits MUST be byte-identical to the Rust and TS canonicalizers
# for the same Value tree. The protocol IS the bytes.
#
# Rules (RFC 8785 + protocol/specs/2026-04-30-canonicalization-grammar.md
# pass 7):
#   - Object keys sorted by Unicode code-point order. Protocol keys are
#     ASCII so byte-order suffices, but we sort by codepoint to match
#     the Rust `cmp` semantics.
#   - Strings: UTF-8 verbatim for U+0080+. Escape `"` and `\` and
#     U+0000..U+001F as `\u00XX` (lowercase hex).
#   - Integers: plain decimal; we only carry int64.
#   - true / false / null verbatim.
#   - No whitespace anywhere.
#
# Hashing: BLAKE3 in 64-byte XOF mode, prefixed `blake3-512:` + lowercase
# hex. Verified against Rust output for the empty input vector.

from __future__ import annotations

from dataclasses import dataclass
import re as _re
from typing import List, Tuple, Union

import blake3 as _blake3

BLAKE3_512_PREFIX = "blake3-512:"


# Value tree -----------------------------------------------------------------


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
    items: Tuple["Value", ...]


@dataclass(frozen=True)
class _Obj:
    # Insertion-order key/value pairs; JCS sorts at emit time.
    entries: Tuple[Tuple[str, "Value"], ...]


Value = Union[_Null, _Bool, _Int, _Str, _Arr, _Obj]


def vnull() -> Value:
    return _Null()


def vbool(b: bool) -> Value:
    return _Bool(bool(b))


def vint(n: int) -> Value:
    if not isinstance(n, int) or isinstance(n, bool):
        raise TypeError("vint requires int")
    return _Int(int(n))


def vstr(s: str) -> Value:
    if not isinstance(s, str):
        raise TypeError("vstr requires str")
    return _Str(s)


def varr(items: List[Value]) -> Value:
    return _Arr(tuple(items))


def vobj(pairs: List[Tuple[str, Value]]) -> Value:
    out: List[Tuple[str, Value]] = []
    for k, v in pairs:
        if not isinstance(k, str):
            raise TypeError("vobj keys must be str")
        out.append((k, v))
    return _Obj(tuple(out))


# JCS encoder ---------------------------------------------------------------


def encode_jcs(v: Value) -> str:
    """Return the canonical JCS encoding of a Value tree as a Python str.

    Caller hashes ``encode_jcs(v).encode("utf-8")``. The encoding is
    byte-identical to the Rust and TS canonicalizers.
    """
    buf: List[str] = []
    _encode(v, buf)
    return "".join(buf)


def _encode(v: Value, out: List[str]) -> None:
    if isinstance(v, _Null):
        out.append("null")
    elif isinstance(v, _Bool):
        out.append("true" if v.value else "false")
    elif isinstance(v, _Int):
        # Plain decimal. Python's int->str is canonical for finite ints.
        out.append(str(v.value))
    elif isinstance(v, _Str):
        _encode_string(v.value, out)
    elif isinstance(v, _Arr):
        out.append("[")
        for i, item in enumerate(v.items):
            if i > 0:
                out.append(",")
            _encode(item, out)
        out.append("]")
    elif isinstance(v, _Obj):
        # Sort by Unicode code-point order. Python's default str sort is
        # codepoint ordinal, which matches Rust's `String::cmp`.
        sorted_entries = sorted(v.entries, key=lambda kv: kv[0])
        out.append("{")
        for i, (k, val) in enumerate(sorted_entries):
            if i > 0:
                out.append(",")
            _encode_string(k, out)
            out.append(":")
            _encode(val, out)
        out.append("}")
    else:
        raise TypeError(f"unknown Value variant: {type(v)!r}")


# The JCS string escape set for this canonicalizer: only `"`, `\`, and the C0
# controls (as lowercase `\u00XX`) are escaped. `/` is NOT escaped, non-ASCII is
# emitted verbatim (including astral characters and lone surrogates, whose
# encoding error surfaces later at `.encode("utf-8")`). Python str -> UTF-8 at
# encode() time produces the same bytes the Rust impl would.
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


def _encode_string(s: str, out: List[str]) -> None:
    # Fast path: nothing to escape (the overwhelming majority of corpus strings
    # are identifiers and CIDs). Byte-identical to the per-character loop, which
    # is kept verbatim as the oracle in
    # tests/test_py_tests_canonicalizer_string_encoder_differential.py.
    if _ESCAPE_SEARCH(s) is None:
        out.append('"' + s + '"')
        return
    out.append('"' + s.translate(_ESCAPE_TABLE) + '"')


# Hash helpers --------------------------------------------------------------


def blake3_512_of(data: bytes) -> str:
    """Self-identifying BLAKE3-512 hash: ``blake3-512:`` + 128 lowercase hex."""
    if not isinstance(data, (bytes, bytearray)):
        raise TypeError("blake3_512_of requires bytes")
    digest = _blake3.blake3(bytes(data)).digest(length=64)
    return BLAKE3_512_PREFIX + digest.hex()


def jcs_hash(v: Value) -> str:
    """Convenience: ``blake3_512_of(encode_jcs(v).encode('utf-8'))``."""
    return blake3_512_of(encode_jcs(v).encode("utf-8"))


def cid_hex(cid: str) -> str | None:
    """Strip the ``blake3-512:`` prefix off a CID string, returning the bare
    128-char hex body. Mirrors ``sugar_canonicalizer::cid_hex`` (Rust): the
    ONE place that owns stripping the algorithm prefix in memory. Returns
    ``None`` if ``cid`` does not carry the canonical colon-prefixed form."""
    if cid.startswith(BLAKE3_512_PREFIX):
        return cid[len(BLAKE3_512_PREFIX) :]
    return None
