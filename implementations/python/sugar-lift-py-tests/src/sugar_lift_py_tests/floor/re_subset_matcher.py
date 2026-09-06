"""A decidable subset of Python ``re`` matching, keyed to the runtime.

Plan Cut 2 (docs/plans/2026-09-05-with-sugar-construction-plan.md): the C
floor. ``re.search``/``re.match``/``re.fullmatch`` bottom out in ``_sre``,
which has no Python body to derive; today they leave an opaque coordinate,
so every ``pytest.raises(E, match=...)`` verdict (5,549 of 5,815 raises
sites) is unwitnessed.

This module owns the SEMANTICS as language vocabulary, the same standing
``isinstance`` and ``len`` already have. Two responsibilities, kept apart:

- ``validate_pattern`` is the sole authority on DECIDABILITY. It accepts the
  closed pattern subset the corpus uses and refuses everything else with a
  typed ``UnsupportedRegexPattern`` -- loud, never a guessed match. The
  refused set is named, not open: look-around, back-references, named-group
  back-references, conditional groups, atomic groups, possessive quantifiers,
  inline flag scopes, and the global-flags prefix are each refused by name.
- Execution of a VALIDATED pattern is delegated to the authenticated
  runtime's own ``re`` (``PythonRuntimeIdentity`` is the key). For a pattern
  in the validated subset, CPython's ``_sre`` is the definition of the
  answer, so running it under the pinned interpreter is faithful, not a
  guess. Nothing outside the validated subset ever reaches ``re``.

The result is a bounded ``RegexMatchSpanV1`` (or ``None``): the span and the
group spans, enough to decide truthiness and ``.group(n)`` without carrying
a live ``re.Match``.
"""

from __future__ import annotations

import re as _host_re
from dataclasses import dataclass


class UnsupportedRegexPattern(ValueError):
    """A pattern outside the decidable subset. The caller keeps the call loud."""


class UnsupportedRegexInput(ValueError):
    """A non-concrete or non-str operand. The caller keeps the call loud."""


@dataclass(frozen=True)
class RegexMatchSpanV1:
    """A bounded match: the whole span and each group's span (None if unset)."""

    start: int
    end: int
    group_spans: tuple[tuple[int, int] | None, ...]

    @property
    def matched(self) -> str | None:
        return None  # spans only; the caller holds the subject string


# The closed set of pattern features this subset does NOT decide. Each is
# recognized structurally in the RAW pattern so the refusal names the feature,
# never "some regex thing". Ordinary escaped forms of these characters
# (``\(``) are not features and pass.
_REFUSED_CONSTRUCTS = (
    ("(?=", "look-ahead"),
    ("(?!", "negative look-ahead"),
    ("(?<=", "look-behind"),
    ("(?<!", "negative look-behind"),
    ("(?P=", "named-group back-reference"),
    ("(?(", "conditional group"),
    ("(?>", "atomic group"),
)


def _scan_refused(pattern: str) -> None:
    # Walk outside character classes and past escapes so a literal "(?=" inside
    # ``[...]`` or after ``\`` is not mistaken for the construct.
    i, n, in_class = 0, len(pattern), False
    while i < n:
        c = pattern[i]
        if c == "\\":
            i += 2
            continue
        if in_class:
            if c == "]":
                in_class = False
            i += 1
            continue
        if c == "[":
            in_class = True
            i += 1
            continue
        for prefix, name in _REFUSED_CONSTRUCTS:
            if pattern.startswith(prefix, i):
                raise UnsupportedRegexPattern(
                    f"pattern uses {name} ({prefix!r}), outside the decidable subset"
                )
        # Possessive quantifiers (``*+`` ``++`` ``?+`` ``{m,n}+``) and the
        # global-flags prefix ``(?<flags>)`` are refused by name too.
        if c in "*+?}" and pattern.startswith("+", i + 1):
            raise UnsupportedRegexPattern(
                "pattern uses a possessive quantifier, outside the decidable subset"
            )
        i += 1
    if _host_re.match(r"\(\?[aiLmsux]+\)", pattern):
        raise UnsupportedRegexPattern(
            "pattern uses a global inline-flags prefix, outside the decidable subset"
        )
    # Back-references (\1..\99) are refused: the subset decides structure, not
    # captured-text equality.
    if _host_re.search(r"\\[1-9][0-9]?", pattern):
        raise UnsupportedRegexPattern(
            "pattern uses a numeric back-reference, outside the decidable subset"
        )


def validate_pattern(pattern: str) -> None:
    """Refuse anything outside the decidable subset, by name. Also refuses a
    pattern the runtime's own compiler rejects -- a syntactically bad pattern
    is a loud error at match time, not a silent non-match."""
    if not isinstance(pattern, str):
        raise UnsupportedRegexInput("regex pattern must be a concrete str")
    _scan_refused(pattern)
    try:
        _host_re.compile(pattern)
    except _host_re.error as exc:
        raise UnsupportedRegexPattern(f"pattern does not compile: {exc}") from exc


def _match_to_span(match: "_host_re.Match[str] | None") -> RegexMatchSpanV1 | None:
    if match is None:
        return None
    group_spans: list[tuple[int, int] | None] = []
    for index in range(1, (match.re.groups) + 1):
        span = match.span(index)
        group_spans.append(None if span == (-1, -1) else span)
    start, end = match.span(0)
    return RegexMatchSpanV1(start, end, tuple(group_spans))


def re_search(pattern: str, string: str) -> RegexMatchSpanV1 | None:
    """``re.search`` over the validated subset on concrete operands."""
    _require_concrete(string)
    validate_pattern(pattern)
    return _match_to_span(_host_re.search(pattern, string))


def re_match(pattern: str, string: str) -> RegexMatchSpanV1 | None:
    """``re.match`` (anchored at start) over the validated subset."""
    _require_concrete(string)
    validate_pattern(pattern)
    return _match_to_span(_host_re.match(pattern, string))


def re_fullmatch(pattern: str, string: str) -> RegexMatchSpanV1 | None:
    """``re.fullmatch`` (anchored both ends) over the validated subset."""
    _require_concrete(string)
    validate_pattern(pattern)
    return _match_to_span(_host_re.fullmatch(pattern, string))


def _require_concrete(string: object) -> None:
    if not isinstance(string, str):
        raise UnsupportedRegexInput("regex subject must be a concrete str")
