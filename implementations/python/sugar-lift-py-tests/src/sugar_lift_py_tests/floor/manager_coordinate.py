"""Tree-native manager / enter-result / open-exit-arg coordinates.

Manager is evaluated **once**; ``ManagerRef(M)`` is the stable receiver for
``__enter__`` / ``__exit__``. Enter-result ``as`` uses ``EnterResultCoordinate``.
Exceptional ``__exit__`` type/traceback holes stay ``OpenExitArg`` — never
silently ``None``.
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

    def attribute(self, name, site):
        # ``x`` itself is the enter result; no .value projection required.
        return super().attribute(name, site)


@dataclass(frozen=True)
class OpenExitArg(FloorValue):
    """Explicit red: exceptional ``__exit__`` arg not constructed.

    Kinds: ``exc_type`` | ``traceback``. Never invent ``None`` for these.
    """

    kind: str
    site: object = dataclass_field(compare=False, default=None)

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor("python:open_exit_arg", [str_const(self.kind)])


@dataclass(frozen=True)
class RaiseWitnessCoordinate(FloorValue):
    """Body raise witness for ``__exit__`` value arg (occurrence, not type-as-id)."""

    occurrence: str
    exception_name: str | None = None
    site: object = dataclass_field(compare=False, default=None)

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:raise_effect_occurrence",
            [str_const(self.occurrence)],
        )
