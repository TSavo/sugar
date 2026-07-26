# SPDX-License-Identifier: MIT OR Apache-2.0
#
# THE ENCODER IS THE PROTOCOL. Two hot-path serializers in the py-tests lift
# were rewritten as pure speed changes:
#
#   1. `canonicalizer._encode_string` -- per-character Python loop -> regex gate
#      plus `str.translate`.
#   2. `ir._rpc_canonical_bytes` -- per-character `any(ord(c) in surrogates)`
#      scan -> strict `str.encode("utf-8")` with the `UnicodeEncodeError`
#      deciding the identical branch.
#
# Neither may move a single byte: every CID pinned in the corpus was minted by
# the pre-rewrite code. The ORACLES below are that pre-rewrite code kept
# verbatim -- not a re-derivation of RFC 8785, but the exact shipped source, so
# byte identity is measured against the thing that minted the pins.
#
# The complexity tooth counts Python-level character visits, NOT wall time. The
# box these run on is loaded and wall times are void.

from __future__ import annotations

import random
import unicodedata

import pytest

from sugar_lift_py_tests import canonicalizer as C
from sugar_lift_py_tests import ir as IR


# --- oracles: the pre-rewrite implementations, verbatim ---------------------


def _oracle_encode_string(s: str, out: list[str]) -> None:
    """The pre-optimization JCS string encoder, verbatim. THE specification."""
    out.append('"')
    for c in s:
        cp = ord(c)
        if c == '"':
            out.append('\\"')
        elif c == "\\":
            out.append("\\\\")
        elif cp < 0x20:
            out.append("\\u00")
            out.append("0123456789abcdef"[(cp >> 4) & 0xF])
            out.append("0123456789abcdef"[cp & 0xF])
        else:
            out.append(c)
    out.append('"')


def _oracle_rpc_canonical_bytes(canonical: str) -> bytes:
    """The pre-optimization surrogate scan, verbatim. THE specification."""
    if not any(0xD800 <= ord(char) <= 0xDFFF for char in canonical):
        return canonical.encode("utf-8")
    safe = "".join(
        "�" if 0xD800 <= ord(char) <= 0xDFFF else char for char in canonical
    )
    return safe.encode("utf-8")


def _call(fn, value):
    """Return ('ok', text) or ('raise', (type, message)) -- error behavior is
    part of the contract, so it is compared, never swallowed."""
    out: list[str] = []
    try:
        fn(value, out)
    except BaseException as exc:  # noqa: BLE001 -- the exception IS the answer
        return ("raise", (type(exc), str(exc)))
    return ("ok", "".join(out))


def _call1(fn, value):
    try:
        return ("ok", fn(value))
    except BaseException as exc:  # noqa: BLE001
        return ("raise", (type(exc), str(exc)))


def _assert_encoder_identical(value: str) -> None:
    old = _call(_oracle_encode_string, value)
    new = _call(C._encode_string, value)
    assert old == new, f"encoder divergence on {value!r}: {old!r} != {new!r}"
    if old[0] == "ok":
        # And identical at the BYTES, which is what gets hashed.
        old_b = _call1(lambda s: s.encode("utf-8"), old[1])
        new_b = _call1(lambda s: s.encode("utf-8"), new[1])
        assert old_b == new_b, f"byte divergence on {value!r}"


def _assert_rpc_bytes_identical(value: str) -> None:
    old = _call1(_oracle_rpc_canonical_bytes, value)
    new = _call1(IR._rpc_canonical_bytes, value)
    assert old == new, f"_rpc_canonical_bytes divergence on {value!r}: {old!r} != {new!r}"


# --- the adversarial corpus ------------------------------------------------

_ADVERSARIAL: list[str] = [
    "",
    "plain",
    "sugar_lift_py_tests.ir",
    "blake3-512:" + "ab" * 64,
    '"',
    "\\",
    '\\"',
    '"\\"',
    "back\\slash",
    "quote\"inside",
    "both\"and\\together",
    "/slash/not/escaped/",
    # every C0 control, individually and together
    *[chr(cp) for cp in range(0x20)],
    "".join(chr(cp) for cp in range(0x20)),
    "\x00\x1f\x7f",
    "\x7f",  # DEL is NOT escaped
    "tab\there",
    "line\nfeed",
    "carriage\rreturn",
    # combining marks and normalization traps
    "é",  # e + combining acute
    unicodedata.normalize("NFC", "é"),
    "ཷ",  # a codepoint whose NFC/NFD differ wildly
    "À́̂̃",
    # astral plane
    "\U0001f600",
    "\U0010ffff",
    "\U0001d11e",  # G-clef
    "a\U0001f600b",
    # non-ASCII BMP
    "é", "中文", "אב", "�", "﻿",
    # lone surrogates -- must raise identically at encode, and be replaced
    # identically by _rpc_canonical_bytes
    "\ud800",
    "\udfff",
    "a\ud800b",
    '"\ud800\\',
    "\x00\ud800\U0001f600",
    # mixed everything
    '{"args":[],"kind":"ctor","name":"f\\"é\U0001f600"}',
]


@pytest.mark.parametrize("value", _ADVERSARIAL, ids=lambda v: repr(v)[:48])
def test_encode_string_byte_identical(value: str) -> None:
    _assert_encoder_identical(value)


@pytest.mark.parametrize("value", _ADVERSARIAL, ids=lambda v: repr(v)[:48])
def test_rpc_canonical_bytes_byte_identical(value: str) -> None:
    _assert_rpc_bytes_identical(value)


def test_random_fuzz_both_faces() -> None:
    """Randomized differential over the whole codepoint space, surrogates and
    escape characters deliberately over-represented."""
    rng = random.Random(20260726)
    alphabet = (
        [chr(cp) for cp in range(0x20)]
        + list('"\\/ aZ09')
        + [chr(cp) for cp in range(0xD800, 0xD810)]
        + [chr(cp) for cp in range(0xDFF0, 0xE000)]
        + ["é", "中", "́", "�", "\U0001f600", "\U0010ffff"]
    )
    for _ in range(3000):
        value = "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 24)))
        _assert_encoder_identical(value)
        _assert_rpc_bytes_identical(value)


def test_full_document_cid_identity() -> None:
    """The CID, not just the string: a canonical document containing every
    adversarial string must hash identically under both encoders."""
    encodable = [s for s in _ADVERSARIAL if not any(0xD800 <= ord(c) <= 0xDFFF for c in s)]
    value = C.varr([C.vstr(s) for s in encodable])
    new_text = C.encode_jcs(value)

    saved = C._encode_string
    C._encode_string = _oracle_encode_string
    try:
        old_text = C.encode_jcs(value)
    finally:
        C._encode_string = saved

    assert old_text == new_text
    assert C.blake3_512_of(IR._rpc_canonical_bytes(old_text)) == C.blake3_512_of(
        IR._rpc_canonical_bytes(new_text)
    )
    assert IR._rpc_canonical_bytes(new_text) == _oracle_rpc_canonical_bytes(new_text)


# --- complexity tooth: counters, not wall time -----------------------------


class _CountingStr(str):
    """A str that records every Python-level character visit made through
    iteration. `str.encode`, `re.search` and `str.translate` do not iterate in
    Python, so a repaired implementation visits zero characters."""

    visits: int

    def __new__(cls, value: str):
        self = super().__new__(cls, value)
        self.visits = 0
        return self

    def __iter__(self):
        for char in str.__iter__(self):
            self.visits += 1
            yield char


def _visits(fn, value: str) -> int:
    probe = _CountingStr(value)
    try:
        fn(probe)
    except BaseException:  # noqa: BLE001 -- counting, not asserting behavior
        pass
    return probe.visits


def _encoder_visits(fn, value: str) -> int:
    probe = _CountingStr(value)
    try:
        fn(probe, [])
    except BaseException:  # noqa: BLE001
        pass
    return probe.visits


def test_complexity_tooth_rpc_canonical_bytes_stops_walking() -> None:
    """The prior bound: `_rpc_canonical_bytes` walked EVERY character of the
    canonical string on every call. Canonical strings nest -- a parent's
    canonical JSON contains all of its descendants' -- so a term table of N
    nodes at depth D walked O(N x D) characters. The repaired bound is zero
    Python-level character visits, independent of length."""
    for length in (1, 100, 10_000, 100_000):
        payload = "x" * length
        assert _visits(_oracle_rpc_canonical_bytes, payload) == length, (
            "oracle must walk every character -- if it does not, the tooth is "
            "measuring the wrong thing"
        )
        assert _visits(IR._rpc_canonical_bytes, payload) == 0, (
            f"_rpc_canonical_bytes walked characters on a clean {length}-char "
            "string; the surrogate scan has returned"
        )

    # The surrogate path is allowed to walk -- it is the rare branch, and it is
    # the branch that must stay byte-identical, not the branch that must be fast.
    surrogate = "x" * 1000 + "\ud800"
    assert _visits(IR._rpc_canonical_bytes, surrogate) > 0
    _assert_rpc_bytes_identical(surrogate)


def test_complexity_tooth_encode_string_stops_walking() -> None:
    """462,239 `_encode_string` calls were on the per-character path. The
    repaired bound is zero Python-level character visits for any string with
    nothing to escape -- which is nearly every corpus string, since they are
    identifiers, sort names, and CIDs."""
    for length in (1, 100, 10_000):
        payload = "a" * length
        assert _encoder_visits(_oracle_encode_string, payload) == length
        assert _encoder_visits(C._encode_string, payload) == 0, (
            f"_encode_string walked characters on a clean {length}-char string; "
            "the per-character loop has returned"
        )

    # Even the escaping path must not iterate in Python: `str.translate` is C.
    assert _encoder_visits(C._encode_string, 'a"b\\c\x00d') == 0


def test_quadratic_shape_of_the_prior_walk() -> None:
    """Names the shape the repair removed: nested canonical strings presented a
    quadratic character mass to the walker as depth grew."""
    walked: list[int] = []
    for depth in (10, 20, 40):
        canonical = '{"kind":"leaf"}'
        total = 0
        for _ in range(depth):
            canonical = '{"args":[' + canonical + '],"kind":"ctor","name":"f"}'
            total += _visits(_oracle_rpc_canonical_bytes, canonical)
        walked.append(total)

    # Doubling the depth more than doubles the walk: the growth is superlinear.
    assert walked[1] > 2 * walked[0]
    assert walked[2] > 2 * walked[1]

    # And the repaired implementation walks nothing at any depth.
    canonical = '{"kind":"leaf"}'
    for _ in range(40):
        canonical = '{"args":[' + canonical + '],"kind":"ctor","name":"f"}'
        assert _visits(IR._rpc_canonical_bytes, canonical) == 0
