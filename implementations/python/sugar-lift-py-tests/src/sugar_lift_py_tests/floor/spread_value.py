from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue


@dataclass(frozen=True)
class SpreadValue(FloorValue):
    """A constructed ``*expr`` awaiting its enclosing syntactic role.

    Python gives the same Starred AST node different wire words in a call and
    a display.  The node constructs this typed value once; only the enclosing
    call/display may project it.  Projecting it as an ordinary value remains a
    floor gap, so a spread can never silently become one argument or element.
    """

    value: FloorValue

    def call_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor

        return ctor("python:starred_arg", [self.value.to_term(owner=owner)])

    def literal_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor

        return ctor("python:starred", [self.value.to_term(owner=owner)])
