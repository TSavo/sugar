"""The floor value for a successful ``re`` match.

A ``re.Match`` is always truthy (an empty match still matches); no match is
``None`` (falsy).  Over a ground pattern and subject the pinned interpreter's
own ``re`` decides the match (``source_call_resolution.re_cited_fold``) and
this floor carries the subject and the spans its ``re.Match`` held, so
``.group(n)`` is decidable without a live ``re.Match``.  Over a subject known
only to be a ``str`` the match is the one the call returned on the face where
its predicate holds: its term is that call's occurrence result and its spans
are not decided.
"""

from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue


@dataclass(frozen=True)
class RegexMatchSpanV1:
    """A bounded match: the whole span and each group's span (None if unset)."""

    start: int
    end: int
    group_spans: tuple[tuple[int, int] | None, ...]

    @classmethod
    def of(cls, match) -> "RegexMatchSpanV1":
        """The spans the pinned interpreter's ``re.Match`` holds."""
        group_spans = tuple(
            None if match.span(index) == (-1, -1) else match.span(index)
            for index in range(1, match.re.groups + 1)
        )
        start, end = match.span(0)
        return cls(start, end, group_spans)


@dataclass(frozen=True)
class ReMatchValue(FloorValue):
    """A successful regex match. Always truthy.

    ``subject`` and ``span`` are the ground match's (``of_host``);
    ``call_result`` is the term of a match whose subject is not ground
    (``undecided``), whose spans nothing here decides."""

    subject: str | None
    span: RegexMatchSpanV1 | None
    call_result: object | None = None

    @classmethod
    def of_host(cls, match) -> "ReMatchValue":
        """The match the pinned interpreter's ``re`` returned over ground
        operands: its subject and spans."""
        return cls(subject=match.string, span=RegexMatchSpanV1.of(match))

    @classmethod
    def undecided(cls, call_result) -> "ReMatchValue":
        """The match a call over a non-ground subject returned, named by that
        call's occurrence result ``call_result``."""
        return cls(subject=None, span=None, call_result=call_result)

    def denotes_value(self) -> bool:
        return True

    def truth(self, site):
        # A Match object is unconditionally truthy -- the presence IS the type.
        from sugar_lift_py_tests.outcome import ExitSet
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        return ExitSet.completed(TrueBoolLiteralSugar(site=site))

    def group_text(self, index: int) -> str | None:
        """``match.group(index)`` as concrete text: group 0 is the whole match,
        1.. are captured groups; an unset optional group is ``None``."""
        if self.span is None or self.subject is None:
            raise LookupError("the match's spans are not decided")
        if index == 0:
            return self.subject[self.span.start : self.span.end]
        spans = self.span.group_spans
        if not 1 <= index <= len(spans):
            raise IndexError("no such group")
        span = spans[index - 1]
        return None if span is None else self.subject[span[0] : span[1]]

    def to_term(self, *, owner: str):
        del owner
        if self.call_result is not None:
            return self.call_result
        from sugar_lift_py_tests.ir import ctor, num, str_const

        return ctor(
            "python:re_match",
            [str_const(self.subject), num(self.span.start), num(self.span.end)],
            symbol_kind="coordinate",
        )
