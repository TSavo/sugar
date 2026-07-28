from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue


@dataclass(frozen=True)
class ExceptionClassValue(FloorValue):
    """Exact installed-source identity of a Python exception subclass."""

    qualified_name: str

    def setitem(self, index, value, site):
        del index, value
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError",
            site=site,
            owner="ExceptionClassValue.setitem",
        )

    def delitem(self, index, site):
        del index
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError",
            site=site,
            owner="ExceptionClassValue.delitem",
        )

    @property
    def name(self) -> str:
        return self.qualified_name

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor("python:exception_type", [str_const(self.qualified_name)])
