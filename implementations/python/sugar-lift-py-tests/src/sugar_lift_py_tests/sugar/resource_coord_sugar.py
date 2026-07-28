"""Sugars for ManagerRef and parametric exit-arg refs (resource with).

These are tree-materialized only. ``WithResourceSugar.desugar`` must not
construct them.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar


@dataclass(frozen=True)
class ManagerRefSugar(ConstructedTermSugar):
    """Tree ``ManagerRef(M)`` — pure manager-slot coordinate."""

    slot_id: str
    site: object = dataclass_field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        return ()

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:manager-reference-construction",
            (self.occurrence_term(owner=owner), str_const(self.slot_id)),
            symbol_kind="coordinate",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx
        from sugar_lift_py_tests.floor.manager_coordinate import ManagerCoordinate

        return Complete(ManagerCoordinate(slot_id=self.slot_id, site=self.site))


@dataclass(frozen=True)
class ExitTypeRefSugar(ConstructedTermSugar):
    """Tree ``ExitTypeRef(X)`` — pure parametric exit-type coordinate."""

    face_id: str
    site: object = dataclass_field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        return ()

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:exit-type-reference-construction",
            (self.occurrence_term(owner=owner), str_const(self.face_id)),
            symbol_kind="coordinate",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx
        from sugar_lift_py_tests.floor.manager_coordinate import ExitTypeCoordinate

        return Complete(ExitTypeCoordinate(face_id=self.face_id, site=self.site))


@dataclass(frozen=True)
class ExitValueRefSugar(ConstructedTermSugar):
    """Tree ``ExitValueRef(X)`` — pure parametric exit-value coordinate."""

    face_id: str
    site: object = dataclass_field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        return ()

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:exit-value-reference-construction",
            (self.occurrence_term(owner=owner), str_const(self.face_id)),
            symbol_kind="coordinate",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx
        from sugar_lift_py_tests.floor.manager_coordinate import ExitValueCoordinate

        return Complete(ExitValueCoordinate(face_id=self.face_id, site=self.site))


@dataclass(frozen=True)
class ExitTracebackRefSugar(ConstructedTermSugar):
    """Tree ``ExitTracebackRef(X)`` — pure parametric exit-traceback coordinate."""

    face_id: str
    site: object = dataclass_field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        return ()

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:exit-traceback-reference-construction",
            (self.occurrence_term(owner=owner), str_const(self.face_id)),
            symbol_kind="coordinate",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx
        from sugar_lift_py_tests.floor.manager_coordinate import (
            ExitTracebackCoordinate,
        )

        return Complete(ExitTracebackCoordinate(face_id=self.face_id, site=self.site))
