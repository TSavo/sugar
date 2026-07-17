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

    def argument_terms(self) -> tuple[Term, ...]:
        from sugar_lift_py_tests.sugar.floor_terms import floor_to_term

        return tuple(
            floor_to_term(argument, owner=f"{self.exception_name} argument")
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
        del index
        from sugar_lift_py_tests.effect import (
            TypeErrorRuntimeEffect,
            runtime_effect_evidence,
        )
        from sugar_lift_py_tests.outcome import Incomplete

        return Incomplete(
            TypeErrorRuntimeEffect(
                "exception subscript type boundary: builtin exception instances "
                f"are not subscriptable; exception={self.exception_name} site={site}",
                **runtime_effect_evidence("py.subscript", self, site),
            )
        )
