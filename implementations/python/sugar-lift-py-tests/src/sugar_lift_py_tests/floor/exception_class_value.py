from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue


@dataclass(frozen=True)
class ExceptionClassValue(FloorValue):
    """Exact installed-source identity of a Python exception subclass."""

    qualified_name: str

    @property
    def name(self) -> str:
        return self.qualified_name

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor("python:exception_type", [str_const(self.qualified_name)])
