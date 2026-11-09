"""``canonical_json_bytes`` writes an undecided document in one pass.

The specification is ``encode_jcs(_json_to_value(value))``: one frozen
``Value`` allocated per JSON node, then a second walk over that tree. Every CID
is taken through it. The one-pass form hands a document to the interpreter's
encoder only where the two cannot differ: every node an exact JSON builtin,
and no string needing an escape. Everything else is still decided by the
specification.

Twins:
  truthful -- an exact, escape-free document is written without the
              specification being consulted, and its bytes and CID are the
              specification's;
  lying    -- a document the interpreter's encoder would silently reshape (a
              tuple, a float, a coerced key, a subclass, a short-form escape)
              is never written by it: the specification encodes or refuses it.
"""

from __future__ import annotations

import enum
import random

import pytest

from sugar_lift_python_source import canonical as C


def _specification(value) -> bytes:
    return C.encode_jcs(C._json_to_value(value)).encode("utf-8")


def _outcome(function, value):
    try:
        return ("bytes", function(value))
    except Exception as error:  # noqa: BLE001 - the outcome IS the comparison
        return ("raised", type(error), str(error))


_ESCAPE_FREE = "abcXYZ019 _-./:{}[],'\x7fé中￿\U0001f600"
_NEEDS_ESCAPE = '"\\\n\r\t\b\f\x00\x1f'


def _random_document(rng: random.Random, alphabet: str, depth: int = 0):
    roll = rng.random()
    if depth >= 4 or roll < 0.35:
        leaf = rng.randrange(5)
        if leaf == 0:
            return None
        if leaf == 1:
            return rng.random() < 0.5
        if leaf == 2:
            return rng.choice((0, 1, -1, 7, -(2**70), 2**70, 10**30))
        return "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 9)))
    if roll < 0.65:
        return [
            _random_document(rng, alphabet, depth + 1)
            for _ in range(rng.randrange(0, 5))
        ]
    return {
        "".join(rng.choice(alphabet) for _ in range(rng.randrange(0, 5))): (
            _random_document(rng, alphabet, depth + 1)
        )
        for _ in range(rng.randrange(0, 6))
    }


def test_escape_free_exact_document_is_written_without_the_specification(
    monkeypatch,
) -> None:
    document = {
        "schema": "constructed-value-v2",
        "arity": 3,
        "children": [
            {"at": 0, "childConstructedValueCid": "blake3-512:" + "ab" * 64},
            {"at": "name", "childConstructedValueCid": "blake3-512:" + "cd" * 64},
        ],
        "localFields": [{"at": 2, "leaf": None}, {"at": 1, "leaf": True}],
        "empty": {},
        "none": [],
        "\U0001f600": -(2**70),
        "￿": "é/\x7f",
    }
    expected = _specification(document)

    def refuse(_value):
        raise AssertionError("the specification was consulted")

    monkeypatch.setattr(C, "_json_to_value", refuse)
    assert C.canonical_json_bytes(document) == expected
    assert C.cid_of_json(document) == C.blake3_512_of(expected)
    # Keys are ordered by code point: U+FFFF sorts before the astral key.
    assert expected.index("￿".encode()) < expected.index("\U0001f600".encode())


def test_fuzzed_escape_free_documents_match_the_specification() -> None:
    rng = random.Random(7559)
    for _ in range(3000):
        document = _random_document(rng, _ESCAPE_FREE)
        assert C.canonical_json_bytes(document) == _specification(document)


def test_fuzzed_documents_with_escapes_match_the_specification() -> None:
    rng = random.Random(7560)
    for _ in range(3000):
        document = _random_document(rng, _ESCAPE_FREE + _NEEDS_ESCAPE)
        assert C.canonical_json_bytes(document) == _specification(document)


def test_a_string_needing_an_escape_is_encoded_by_the_specification(
    monkeypatch,
) -> None:
    # The interpreter's encoder would write the two-character short form.
    assert C.canonical_json_bytes({"k": "a\nb"}) == b'{"k":"a\\u000ab"}'
    assert C.canonical_json_bytes(["\t", "\b", "\f", "\r"]) == (
        b'["\\u0009","\\u0008","\\u000c","\\u000d"]'
    )
    assert C.canonical_json_bytes({'q"': "\\"}) == b'{"q\\"":"\\\\"}'

    consulted = []
    specification = C._json_to_value

    def witness(value):
        consulted.append(value)
        return specification(value)

    monkeypatch.setattr(C, "_json_to_value", witness)
    C.canonical_json_bytes({"k": "a\nb"})
    # The whole document went to the specification (which then recursed).
    assert consulted[0] == {"k": "a\nb"}


class _Colour(enum.IntEnum):
    RED = 1


class _Word(str):
    pass


class _Rows(list):
    pass


class _Table(dict):
    pass


@pytest.mark.parametrize(
    "document",
    [
        (1, 2),  # the interpreter's encoder would write an array
        {"k": (1, 2)},
        1.0,  # ... a float
        [float("nan")],
        {1: "a"},  # ... the key "1"
        {True: "a"},  # ... the key "true"
        {None: "a"},  # ... the key "null"
        {"a": {2.5: "b"}},
        {"k": b"bytes"},
        {"k": {1, 2}},
        object(),
        _Colour.RED,
        {"k": _Colour.RED},
        _Word("w"),
        {_Word("k"): "v"},
        _Rows([1, "a"]),
        _Table({"k": "v"}),
        {"deep": [[[{"k": [(1,)]}]]]},
    ],
    ids=repr,
)
def test_a_document_outside_the_exact_builtins_is_decided_by_the_specification(
    document,
) -> None:
    assert _outcome(C.canonical_json_bytes, document) == _outcome(
        _specification, document
    )


def test_what_the_specification_refuses_stays_refused() -> None:
    for document in ((1, 2), 1.0, {1: "a"}, {True: "a"}, {None: "a"}, {"k": {1}}):
        with pytest.raises(TypeError):
            C.canonical_json_bytes(document)
    # A lone surrogate passes both encoders and fails at the bytes, as before.
    with pytest.raises(UnicodeEncodeError):
        C.canonical_json_bytes({"k": "\ud800"})
    with pytest.raises(UnicodeEncodeError):
        _specification({"k": "\ud800"})
