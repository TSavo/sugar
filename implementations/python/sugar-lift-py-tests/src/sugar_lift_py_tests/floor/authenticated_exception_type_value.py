from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.ir import Term

from .floor_value import FloorValue


@dataclass(frozen=True)
class AuthenticatedExceptionTypeValue(FloorValue):
    """A type operand plus its source-authenticated exception-class identity."""

    value: FloorValue
    identity: Term
    mro: tuple[Term, ...] | None = None

    def to_term(self, *, owner: str):
        return self.value.to_term(owner=owner)

    def exception_type_identity(self) -> Term:
        return self.identity

    def exception_type_mro(self) -> tuple[Term, ...] | None:
        return self.mro
