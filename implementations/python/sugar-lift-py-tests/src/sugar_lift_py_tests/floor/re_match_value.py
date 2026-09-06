"""The floor value for a successful ``re`` match over the decidable subset.

Plan Cut 2. A ``re.Match`` is always truthy (an empty match still matches);
no match is ``None`` (falsy). This floor carries the bounded span testimony
from ``re_subset_matcher`` plus the concrete subject, so truthiness is
decided now and ``.group(n)`` is decidable later without a live re.Match.
"""

from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue
from .re_subset_matcher import RegexMatchSpanV1


@dataclass(frozen=True)
class ReMatchValue(FloorValue):
    """A successful regex match: subject + bounded spans. Always truthy."""

    subject: str
    span: RegexMatchSpanV1

    def denotes_value(self) -> bool:
        return True

    def truth(self, site):
        # A Match object is unconditionally truthy -- the presence IS the type.
        from sugar_lift_py_tests.outcome import Complete
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        return Complete(TrueBoolLiteralSugar(site=site))

    def group_text(self, index: int) -> str | None:
        """``match.group(index)`` as concrete text: group 0 is the whole match,
        1.. are captured groups; an unset optional group is ``None``."""
        if index == 0:
            return self.subject[self.span.start : self.span.end]
        spans = self.span.group_spans
        if not 1 <= index <= len(spans):
            raise IndexError("no such group")
        span = spans[index - 1]
        return None if span is None else self.subject[span[0] : span[1]]

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor, num, str_const

        return ctor(
            "python:re_match",
            [str_const(self.subject), num(self.span.start), num(self.span.end)],
            symbol_kind="coordinate",
        )
