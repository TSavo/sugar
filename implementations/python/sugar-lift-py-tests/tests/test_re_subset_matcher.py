"""Plan Cut 2: the decidable re subset — matcher core twins.

Truthful: patterns in the subset match exactly what the runtime's re does.
Lying/refusal: every construct outside the subset refuses BY NAME, never a
guessed non-match; symbolic/non-str operands refuse; a bad pattern is loud.
"""

from __future__ import annotations

import re

import pytest

from sugar_lift_py_tests.floor.re_subset_matcher import (
    RegexMatchSpanV1,
    UnsupportedRegexInput,
    UnsupportedRegexPattern,
    re_fullmatch,
    re_match,
    re_search,
    validate_pattern,
)

# The corpus subset: literals, . ^ $, quantifiers, classes, groups, \d\w\s\b, |.
SUBSET_CASES = [
    ("abc", "xabcy"),
    ("a.c", "a-c"),
    ("^start", "start here"),
    ("end$", "at the end"),
    (" a+b*c?", " aaab"),
    (r"\d{2,4}", "id=1234 done"),
    (r"[A-Za-z_]\w*", "name0 = 1"),
    ("(foo|bar)baz", "well barbaz"),
    (r"(?:ab)+", "ababab"),
    (r"\bword\b", "a word here"),
    ("A value is being set", "A value is being set on a copy"),
    ("", "anything"),
    ("nomatch", "xxxxx"),
]


@pytest.mark.parametrize("pattern,subject", SUBSET_CASES)
def test_subset_matches_agree_with_the_runtime(pattern, subject) -> None:
    for ours, host in (
        (re_search(pattern, subject), re.search(pattern, subject)),
        (re_match(pattern, subject), re.match(pattern, subject)),
        (re_fullmatch(pattern, subject), re.fullmatch(pattern, subject)),
    ):
        if host is None:
            assert ours is None
        else:
            assert isinstance(ours, RegexMatchSpanV1)
            assert (ours.start, ours.end) == host.span(0)
            assert ours.group_spans == tuple(
                (None if host.span(i) == (-1, -1) else host.span(i))
                for i in range(1, host.re.groups + 1)
            )


def test_group_spans_are_carried() -> None:
    m = re_search(r"(\d+)-(\d+)", "id 12-345 x")
    assert m is not None and m.group_spans == ((3, 5), (6, 9))
    subject = "id 12-345 x"
    assert subject[slice(*m.group_spans[0])] == "12"
    assert subject[slice(*m.group_spans[1])] == "345"


REFUSED = [
    ("(?=foo)", "look-ahead"),
    ("(?!foo)", "negative look-ahead"),
    ("(?<=foo)", "look-behind"),
    ("(?<!foo)", "negative look-behind"),
    (r"(?P<n>a)(?P=n)", "named-group back-reference"),
    (r"(a)\1", "numeric back-reference"),
    ("(?i)abc", "global inline-flags prefix"),
    ("a*+", "possessive quantifier"),
]


@pytest.mark.parametrize("pattern,name", REFUSED)
def test_out_of_subset_refuses_by_name(pattern, name) -> None:
    with pytest.raises(UnsupportedRegexPattern, match=re.escape(name)):
        validate_pattern(pattern)
    with pytest.raises(UnsupportedRegexPattern):
        re_search(pattern, "whatever")


def test_escaped_lookalikes_are_not_features() -> None:
    # ``\(?=`` etc. are literal characters, not constructs, and pass.
    for pattern in (r"\(\?=x", r"a\\b", r"[(?=]", "(?:ok)"):
        validate_pattern(pattern)


def test_a_bad_pattern_is_loud_not_a_silent_non_match() -> None:
    with pytest.raises(UnsupportedRegexPattern, match="does not compile"):
        validate_pattern("(unclosed")


def test_non_concrete_operands_refuse() -> None:
    with pytest.raises(UnsupportedRegexInput):
        re_search("abc", object())  # type: ignore[arg-type]
    with pytest.raises(UnsupportedRegexInput):
        re_search(object(), "abc")  # type: ignore[arg-type]


def test_pytest_raises_match_shape_is_decided() -> None:
    """The prize: pytest.raises(E, match=P) truthiness on a concrete message."""
    message = "A value is being set on a copy of a DataFrame"
    assert re_search("A value is being set", message) is not None  # truthful
    assert re_search("A value is NOT being set", message) is None  # lying twin
