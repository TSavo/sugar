"""Tree-native manager / enter-result / exit-face coordinates.

Manager is evaluated **once**; ``ManagerRef(M)`` is the stable receiver for
``__enter__`` / ``__exit__``. Exit args are parametric
``ExitTypeRef(X)`` / ``ExitValueRef(X)`` / ``ExitTracebackRef(X)`` — pure
coordinates; face testimony authenticates them under guards.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from .floor_value import FloorValue


@dataclass(frozen=True)
class ManagerCoordinate(FloorValue):
    """Once-evaluated manager identity: ``python:manager_slot(M)``."""

    slot_id: str
    site: object = dataclass_field(compare=False, default=None)

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor("python:manager_slot", [str_const(self.slot_id)])


@dataclass(frozen=True)
class EnterResultCoordinate(FloorValue):
    """``with m as x`` enter-result coordinate: ``python:enter_result(E)``."""

    slot_id: str
    site: object = dataclass_field(compare=False, default=None)

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor("python:enter_result", [str_const(self.slot_id)])


@dataclass(frozen=True)
class ExitTypeCoordinate(FloorValue):
    """Parametric ``__exit__`` type arg: ``python:exit_type(X)``."""

    face_id: str
    site: object = dataclass_field(compare=False, default=None)

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor("python:exit_type", [str_const(self.face_id)])

    def test_python_subtype(self, supertype, site):
        from sugar_lift_py_tests.floor import ClassValue, SymbolicValue, TupleValue
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.ir import atomic
        from sugar_lift_py_tests.outcome import Complete

        if type(supertype) is TupleValue:
            return supertype.test_python_subtype(self, site)
        if not isinstance(supertype, (ClassValue, SymbolicValue)):
            return _dynamic_subtype_operand(self, supertype, site)
        return Complete(
            PredicateValue(
                atomic(
                    "python.subtype",
                    [
                        self.to_term(owner="python.issubclass subtype"),
                        supertype.to_term(owner="python.issubclass supertype"),
                    ],
                ),
                site,
                operand_callsites=(*self.callsites(), *supertype.callsites()),
            )
        )


@dataclass(frozen=True)
class ExitValueCoordinate(FloorValue):
    """Parametric ``__exit__`` value arg: ``python:exit_value(X)``."""

    face_id: str
    site: object = dataclass_field(compare=False, default=None)

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor("python:exit_value", [str_const(self.face_id)])

    def attribute(self, name, site):
        """Project an attribute from the real parametric exception value."""
        del site
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
        from sugar_lift_py_tests.ir import ctor, str_const
        from sugar_lift_py_tests.outcome import Complete

        return Complete(
            SymbolicValue(
                ctor("py.getattr", [self.to_term(owner="exit"), str_const(name)])
            )
        )


@dataclass(frozen=True)
class ExitTracebackCoordinate(FloorValue):
    """Parametric ``__exit__`` traceback arg: ``python:exit_traceback(X)``."""

    face_id: str
    site: object = dataclass_field(compare=False, default=None)

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor("python:exit_traceback", [str_const(self.face_id)])


def _dynamic_subtype_operand(subtype, supertype, site):
    del subtype
    from sugar_lift_py_tests.gap.panic import construction_panic_gap

    construction_panic_gap(
        owner="ExitTypeCoordinate.test_python_subtype",
        blame=str(site),
        observed=type(supertype).__name__,
        requested="authenticated class, tuple-of-classes, or symbolic type operand",
        fix="construct the Python type operand or keep issubclass loudly unsupported",
    )
