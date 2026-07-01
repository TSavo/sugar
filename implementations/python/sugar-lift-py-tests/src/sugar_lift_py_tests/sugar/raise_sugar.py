from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.outcome import Incomplete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class RaiseSugar(Sugar, role=SugarRole.STATEMENT):
    """`raise ...` -- a statement that IS an effect.

    It produces no value and warrants no constraint: it transfers control out of the
    function, so every statement after it is unreachable. That is exactly an Incomplete
    effect, so desugar is one line: `return Incomplete(RaiseEffect)`. The block reducing
    it matches the Incomplete and bubbles it upward, doing no work past it -- the same
    short-circuit as any other effect (division by zero, etc.). No reduction, no
    detection: the sugar simply is the Incomplete.
    """

    exception_name: str | None = None
    blame: str | None = None

    @classmethod
    def owns(cls, fragment) -> bool:
        return fragment.observed == "Raise"

    @classmethod
    def build(cls, fragment, ctx) -> "RaiseSugar":
        if fragment.observed != "Raise":
            raise TypeError("RaiseSugar claim built a non-raise statement")
        terms = fragment.terms()
        return cls(
            exception_name=_exception_name(terms[0]) if terms else None,
            blame=fragment.blame,
        )

    def desugar(self, ctx=None) -> Outcome:
        return Incomplete(RaiseEffect(self.exception_name, self.blame))


def _exception_name(site) -> str | None:
    if site.observed == "Call":
        return site.call_qualified_target_name() or site.call_target_name()
    if site.observed == "Name":
        return site.name_id()
    if site.observed == "Attribute":
        receiver = _exception_name(site.attr_receiver())
        if receiver is not None:
            return f"{receiver}.{site.attr_name()}"
    return None
