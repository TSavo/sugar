"""Disposition routing twins for source-derived resource managers."""

from types import SimpleNamespace

from sugar_lift_py_tests.context_manager_contract import EffectMatcher, Suppresses
from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.floor import BlockValue, TermValue
from sugar_lift_py_tests.outcome import Complete, Halted, Incomplete
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.with_source_resource_sugar import (
    WithSourceResourceSugar,
)


class _FixedSugar(Sugar):
    def __init__(self, outcome):
        self.outcome = outcome

    def desugar(self, ctx=None):
        del ctx
        return self.outcome

    @classmethod
    def witnesses(cls):
        return ()


class _CompletedProtocol:
    def enter_outcome(self, ctx=None):
        del ctx
        return Complete(TermValue(2))

    def exit_outcome(self, ctx=None):
        del ctx
        return Complete(BlockValue((), can_fall_through=True))


def test_summary_suppresses_disposition_consumes_matching_body_halt():
    disposition = Suppresses(EffectMatcher(kind="raise", name="ValueError"))
    summary = SimpleNamespace(
        semantics=SimpleNamespace(exit=SimpleNamespace(disposition=disposition))
    )
    sugar = WithSourceResourceSugar(
        manager=_FixedSugar(Complete(TermValue(1))),
        protocol=_CompletedProtocol(),
        summary=summary,
        body=(
            _FixedSugar(
                Incomplete(
                    RaiseEffect(
                        exception_name="ValueError", occurrence="resource.py:4:8"
                    )
                )
            ),
        ),
        manager_slot_id="manager-slot",
        enter_slot_id=None,
        exit_face_id="exit-face",
        site="resource.py:3:4",
    )

    exits = sugar.desugar().exits

    assert exits
    assert not any(
        isinstance(face, Halted)
        and getattr(face.effect, "exception_name", None) == "ValueError"
        for face in exits
    )
