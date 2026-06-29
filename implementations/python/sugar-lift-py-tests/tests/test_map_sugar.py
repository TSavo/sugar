"""MapSugar is a COMPOSER: it applies WHATEVER body the lambda was handed to each
element of WHATEVER receiver array, pointwise. It is agnostic to the body sugar --
identity (Name), add (Add), and constant (literal) bodies all compose the SAME Map,
with no Map change. New body operations (`*`, `[]`, string concat) are MORE SUGAR
(a leaf body), never a smarter Map.

The composed reduction is the pointwise equality of the transformed array against
the asserted expected: all-equal => sat, any unequal => the discrimination (no
false discharge). This is the unit test for the composition the user described:
pin the leaves (array, lambda, add) then compose them here."""
from __future__ import annotations

from factory_reduce import array_map_pairs


def _pairs(body: str, receiver: str, expected: str):
    return array_map_pairs(f"def t():\n    assert {receiver}.map({body}) == {expected}\n")


def test_map_applies_whatever_body_pointwise_over_whatever_receiver():
    cases = [
        # (lambda body, receiver array, expected) -- the body sugar varies, Map does not
        ("lambda x: x", "[1, 2, 3]", "[1, 2, 3]"),  # identity body (NameSugar)
        ("lambda x: x + 1", "[1, 2, 3]", "[2, 3, 4]"),  # add body (AddSugar)
        ("lambda x: 7", "[1, 2, 3]", "[7, 7, 7]"),  # constant body (literal)
        ("lambda x: x + 5", "[10, 20]", "[15, 25]"),  # add body, different receiver
    ]
    for body, receiver, expected in cases:
        pairs = _pairs(body, receiver, expected)
        assert all(left == right for left, right in pairs), (body, pairs)


def test_map_discriminates_a_wrong_expected():
    # one element disagrees -> an unequal pair -> unsat. Map does not fudge it.
    pairs = _pairs("lambda x: x + 1", "[1, 2, 3]", "[2, 3, 99]")
    assert any(left != right for left, right in pairs)
