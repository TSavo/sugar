# SPDX-License-Identifier: MIT OR Apache-2.0
#
# THE ENCODER IS THE PROTOCOL. `canonical._encode_string` was rewritten from a
# per-character Python loop into a regex-gated fast path plus `str.translate`.
# The rewrite is a pure speed change: every supported string must produce
# byte-identical canonical JSON, and every canonical document must produce an
# identical CID, before and after. These twins are the standing proof.
#
# The ORACLE is the per-character loop itself, kept here verbatim. It is not a
# re-derivation of RFC 8785 -- it is the exact code that shipped, so byte
# identity is measured against the thing that minted every pinned CID.

from __future__ import annotations

import random
import unicodedata

import pytest

from sugar_lift_python_source import canonical as C


def _oracle_encode_string(value: str, out: list[str]) -> None:
    """The pre-optimization encoder, verbatim. THE specification."""
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
        elif 0xD800 <= codepoint <= 0xDFFF:
            # A lone surrogate has no UTF-8 bytes: its code-point escape is
            # its canonical spelling (#7757). No other string changed.
            out.append(f"\\u{codepoint:04x}")
        else:
            out.append(char)
    out.append('"')


def _call(fn, value):
    """Return ('ok', text) or ('raise', (type, message)) -- error behavior is
    part of the contract, so it is compared, never swallowed."""
    out: list[str] = []
    try:
        fn(value, out)
    except BaseException as exc:  # noqa: BLE001 -- the exception IS the answer
        return ("raise", (type(exc), str(exc)))
    return ("ok", "".join(out))


def _assert_identical(value: str) -> None:
    old = _call(_oracle_encode_string, value)
    new = _call(C._encode_string, value)
    assert old == new, f"encoder divergence on {value!r}: {old!r} != {new!r}"
    if old[0] == "ok":
        # And identical at the BYTES, which is what gets hashed.
        try:
            old_bytes, old_err = old[1].encode("utf-8"), None
        except BaseException as exc:  # noqa: BLE001
            old_bytes, old_err = None, (type(exc), str(exc))
        try:
            new_bytes, new_err = new[1].encode("utf-8"), None
        except BaseException as exc:  # noqa: BLE001
            new_bytes, new_err = None, (type(exc), str(exc))
        assert (old_bytes, old_err) == (new_bytes, new_err)


# --- explicit escape classes ------------------------------------------------


def test_quote_is_escaped():
    assert C.encode_jcs(C.vstr('a"b')) == '"a\\"b"'
    _assert_identical('a"b')


def test_backslash_is_escaped():
    assert C.encode_jcs(C.vstr("a\\b")) == '"a\\\\b"'
    _assert_identical("a\\b")


def test_solidus_is_NOT_escaped():
    # JCS does not escape `/`, and neither does this canonicalizer. A change
    # here would repin every CID carrying a path.
    assert C.encode_jcs(C.vstr("a/b")) == '"a/b"'
    _assert_identical("a/b")


def test_c0_controls_use_lowercase_u00xx_not_short_forms():
    # \b \f \n \r \t are NOT emitted as short escapes -- they are \u00XX.
    assert C.encode_jcs(C.vstr("\b\f\n\r\t")) == '"\\u0008\\u000c\\u000a\\u000d\\u0009"'
    for cp in range(0x20):
        value = chr(cp)
        assert C.encode_jcs(C.vstr(value)) == f'"\\u00{cp:02x}"'
        _assert_identical(value)


def test_del_and_high_ascii_are_verbatim():
    assert C.encode_jcs(C.vstr("\x7f")) == '"\x7f"'
    for cp in range(0x20, 0x100):
        _assert_identical(chr(cp))


def test_every_byte_valued_codepoint_matches_oracle():
    for cp in range(0x100):
        _assert_identical(chr(cp))


def test_astral_characters_are_verbatim_not_surrogate_pairs():
    for value in ["😀🎉🔥", "𝔘𝔫𝔦", "\U0002f804", "𠜎𠜱𠝹", "👨‍👩‍👧‍👦"]:
        assert C.encode_jcs(C.vstr(value)) == f'"{value}"'
        _assert_identical(value)


def test_combining_forms_are_not_normalized():
    decomposed = "é"
    precomposed = unicodedata.normalize("NFC", decomposed)
    assert decomposed != precomposed
    assert C.encode_jcs(C.vstr(decomposed)) != C.encode_jcs(C.vstr(precomposed))
    _assert_identical(decomposed)
    _assert_identical(precomposed)


def test_zero_width_and_bidi_controls_are_verbatim():
    for value in ["​‌‍﻿", "‪‫‬‭‮", "⁦⁧⁨⁩", "؜"]:
        assert C.encode_jcs(C.vstr(value)) == f'"{value}"'
        _assert_identical(value)


def test_lone_surrogates_are_written_as_their_code_point_escape():
    # A Python str may hold a surrogate code point no UTF-8 sequence spells
    # (``"\ud83d"`` in pandas source). It is a value like any other, so it has
    # canonical bytes: its lowercase code-point escape, which is ASCII.
    for value, spelled in [
        ("\ud800", '"\\ud800"'),
        ("\udfff", '"\\udfff"'),
        ("a\udc00b", '"a\\udc00b"'),
        ("\ud83d", '"\\ud83d"'),
        ("\ud83d\ude00", '"\\ud83d\\ude00"'),
    ]:
        _assert_identical(value)
        assert C.encode_jcs(C.vstr(value)) == spelled
        assert C.canonical_json_bytes(value) == spelled.encode("ascii")
        assert C.canonical_json_bytes({"k": [value]}) == (
            b'{"k":[' + spelled.encode("ascii") + b"]}"
        )


def test_a_lone_surrogate_never_shares_bytes_with_another_string():
    # Lying twin: the escape text spelled out with a real backslash, and the
    # astral character the pair would name, are different strings with
    # different bytes and different CIDs.
    lone = "\ud83d\ude00"
    for other in ["\\ud83d\\ude00", "\U0001f600", "ud83dude00"]:
        assert C.canonical_json_bytes(other) != C.canonical_json_bytes(lone)
        assert C.cid_of_json(other) != C.cid_of_json(lone)


def test_empty_and_pure_cid_strings():
    _assert_identical("")
    assert C.encode_jcs(C.vstr("")) == '""'
    _assert_identical("blake3-512:" + "ab12" * 32)


def test_very_long_strings():
    for value in ["x" * 200_000, 'a"b\\c\n' * 20_000, "日" * 100_000]:
        _assert_identical(value)


# --- differential fuzz ------------------------------------------------------

_ALPHABET = (
    [chr(c) for c in range(0x00, 0x80)]
    + ['"', "\\", "/", "\n", "\t"] * 6
    + [chr(c) for c in (0xA9, 0x2028, 0x2029, 0xFEFF, 0x200B, 0x0301, 0x05D0, 0x4E2D)]
    + [chr(c) for c in (0x1F600, 0x1D11E, 0x2F804, 0x10FFFF)]
    + [chr(c) for c in (0xD800, 0xDBFF, 0xDC00, 0xDFFF)]  # lone surrogates
)


def test_differential_fuzz_strings():
    rng = random.Random(20260724)
    for _ in range(20_000):
        length = rng.randint(0, 40)
        _assert_identical("".join(rng.choice(_ALPHABET) for _ in range(length)))


def _oracle_canonical_json_bytes(value):
    saved = C._encode_string
    C._encode_string = _oracle_encode_string
    try:
        return C.canonical_json_bytes(value)
    finally:
        C._encode_string = saved


def _holds_lone_surrogate(doc: dict) -> bool:
    texts = list(doc)
    for value in doc.values():
        if isinstance(value, str):
            texts.append(value)
        elif isinstance(value, list):
            texts.extend(value)
    return any(0xD800 <= ord(char) <= 0xDFFF for text in texts for char in text)


def test_differential_fuzz_whole_documents_and_cids():
    """T's gate: complete canonical DOCUMENTS and resulting CIDs, not merely
    isolated strings."""
    rng = random.Random(981_2026)
    checked = with_surrogate = 0
    for _ in range(2_000):
        doc = {}
        for _ in range(rng.randint(0, 6)):
            key = "".join(rng.choice(_ALPHABET) for _ in range(rng.randint(1, 12)))
            pick = rng.randint(0, 4)
            if pick == 0:
                doc[key] = None
            elif pick == 1:
                doc[key] = rng.choice([True, False])
            elif pick == 2:
                doc[key] = rng.randint(-(2**70), 2**70)
            elif pick == 3:
                doc[key] = "".join(
                    rng.choice(_ALPHABET) for _ in range(rng.randint(0, 20))
                )
            else:
                doc[key] = [
                    "".join(rng.choice(_ALPHABET) for _ in range(5))
                    for _ in range(rng.randint(0, 4))
                ]
        try:
            old_bytes, old_err = _oracle_canonical_json_bytes(doc), None
        except BaseException as exc:  # noqa: BLE001
            old_bytes, old_err = None, (type(exc), str(exc))
        try:
            new_bytes, new_err = C.canonical_json_bytes(doc), None
        except BaseException as exc:  # noqa: BLE001
            new_bytes, new_err = None, (type(exc), str(exc))
        assert old_err is None and new_err is None, f"refused: {old_err} {new_err}"
        assert old_bytes == new_bytes, "document byte divergence"
        assert C.cid_of_json(doc) == C.blake3_512_of(old_bytes)
        checked += 1
        if _holds_lone_surrogate(doc):
            with_surrogate += 1
    assert (
        checked > with_surrogate > 0
    ), "fuzz must cover documents with and without a lone surrogate"


def test_realistic_preimage_documents_keep_their_cids():
    """Preimage shapes taken from the construction pipeline: nested objects,
    CID references, source spans, unicode operator names."""
    docs = [
        {
            "kind": "BinOp",
            "op": "≥",
            "left": {"kind": "Name", "id": "value", "ref": "blake3-512:" + "3f" * 64},
            "right": {"kind": "Constant", "value": "0"},
            "span": {"start": 12, "end": 44},
            "file": "pandas/core/generic.py",
        },
        {
            "coordinate": ["blake3-512:" + "ab" * 64, "reporter/0", "control:none"],
            "testimony": {"present": True, "note": 'quote " and backslash \\ and \n'},
        },
        {
            "docstring": "Return the sum.\n\n    Parameters\n    ----------\n    x : int\n"
        },
        {"names": ["≤", "≠", "∀", "日本語", "😀"], "empty": "", "nested": [[], [[]]]},
    ]
    for doc in docs:
        assert C.canonical_json_bytes(doc) == _oracle_canonical_json_bytes(doc)
        assert C.cid_of_json(doc) == C.blake3_512_of(_oracle_canonical_json_bytes(doc))


def test_fast_path_gate_agrees_with_the_escape_set():
    """The regex gate must fire on exactly the characters the loop escapes --
    never fewer (silent corruption), never a claim of more than it handles."""
    for cp in range(0x11000):
        char = chr(cp)
        needs_escape = char in ('"', "\\") or cp < 0x20 or 0xD800 <= cp <= 0xDFFF
        assert (C._ESCAPE_SEARCH(char) is not None) == needs_escape, hex(cp)
