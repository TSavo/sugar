"""Sugars for ManagerRef / open exit args / raise witnesses (resource with)."""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class ManagerRefSugar(Sugar):
    """Tree ``ManagerRef(M)`` — pure manager-slot coordinate."""

    slot_id: str
    site: object = dataclass_field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx
        from sugar_lift_py_tests.floor.manager_coordinate import ManagerCoordinate

        return Complete(ManagerCoordinate(slot_id=self.slot_id, site=self.site))


@dataclass(frozen=True)
class OpenExitArgSugar(Sugar):
    """Exceptional ``__exit__`` arg left explicitly open (type / tb / val)."""

    kind: str
    site: object = dataclass_field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx
        from sugar_lift_py_tests.floor.manager_coordinate import OpenExitArg

        return Complete(OpenExitArg(kind=self.kind, site=self.site))


@dataclass(frozen=True)
class RaiseWitnessSugar(Sugar):
    """Body raise occurrence as ``__exit__`` exception-value argument."""

    occurrence: str
    exception_name: str | None = None
    site: object = dataclass_field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx
        from sugar_lift_py_tests.floor.manager_coordinate import RaiseWitnessCoordinate

        return Complete(
            RaiseWitnessCoordinate(
                occurrence=self.occurrence,
                exception_name=self.exception_name,
                site=self.site,
            )
        )
