from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.floor import RaiseValue
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witness_examples import raise_try_return_witness


@dataclass(frozen=True)
class RaiseSugar(Sugar, role=SugarRole.STATEMENT):
    """`raise ...` -- a statement that emits a routeable Python raise exit.

    A raise is Python control flow, not a runtime effect. The block frontier carries it
    as a floor value so `TrySugar` can curry a matching handler over the same guarded
    path. Residual raises are lowered/refused later as effects.
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

    @classmethod
    def witnesses(cls):
        return raise_try_return_witness()

    def desugar(self, ctx=None) -> Outcome:
        return Complete(
            RaiseValue(RaiseEffect(self.exception_name, self.blame), scope=ctx)
        )


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
