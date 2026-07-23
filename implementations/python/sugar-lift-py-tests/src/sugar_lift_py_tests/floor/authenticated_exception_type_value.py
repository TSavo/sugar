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

    def test_python_subtype(self, supertype, site):
        from sugar_lift_py_tests.floor.authenticated_exception_type_value import (
            AuthenticatedExceptionTypeValue,
        )
        from sugar_lift_py_tests.outcome import Complete
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )
        from sugar_source_tree.panic import SugarNotWritten

        if not isinstance(supertype, AuthenticatedExceptionTypeValue):
            raise SugarNotWritten(
                owner="AuthenticatedExceptionTypeValue.test_python_subtype",
                observed=type(supertype).__name__,
                requested="authenticated exception type operand",
                fix="construct the handler type through its lexical coordinate",
            )
        return Complete(
            TrueBoolLiteralSugar(site)
            if self.identity == supertype.identity
            or (self.mro is not None and supertype.identity in self.mro)
            else FalseBoolLiteralSugar(site)
        )
