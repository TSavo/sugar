from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.ir import Term

from .floor_value import FloorValue


@dataclass(frozen=True)
class ExceptionValue(FloorValue):
    """A statically constructed instance of an exact builtin exception class."""

    exception_name: str
    arguments: tuple[FloorValue, ...]
    site: object = dataclass_field(compare=False)

    def setitem(self, index, value, site, ctx):
        del index, value, ctx
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError", site=site, owner="ExceptionValue.setitem"
        )

    def delitem(self, index, site, ctx):
        del index, ctx
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError", site=site, owner="ExceptionValue.delitem"
        )

    def argument_terms(self) -> tuple[Term, ...]:

        return tuple(
            argument.to_term(owner=f"{self.exception_name} argument")
            for argument in self.arguments
        )

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:exception",
            [str_const(self.exception_name), *self.argument_terms()],
        )

    def subscript(self, index, site):
        """``exc[i]`` on an exact builtin exception instance raises TypeError.

        No builtin ``BaseException`` subclass defines ``__getitem__`` (Python 3
        removed ``BaseException.__getitem__``), and this value is an exact
        builtin class, so the exceptional exit is decided at lift time. It is a
        ground ``RaiseEffect`` like ``setitem``/``delitem``, never a
        ``RuntimeEffect``: a RuntimeEffect is an undecided runtime boundary,
        and typing a decided raise as one hides it from ``except`` and from a
        With's ``__exit__``.
        """
        del index
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError", site=site, owner="ExceptionValue.subscript"
        )
