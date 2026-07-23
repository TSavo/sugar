from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class AuthenticatedExceptionTypeSugar(Sugar):
    value: Sugar
    identity: object
    mro: tuple | None = None
    site: object = dataclass_field(compare=False, default=None)
    class_value: object | None = dataclass_field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        from sugar_lift_py_tests.sugar.witnesses import _call_pair

        return _call_pair(
            name="authenticated_exception_type",
            owner_sugar="AuthenticatedExceptionTypeSugar",
            truthful="def f(x):\n    return x\n",
            lying="def f(x):\n    return 0\n",
        )

    def desugar(self, ctx=None):
        from sugar_lift_py_tests.floor.authenticated_exception_type_value import (
            AuthenticatedExceptionTypeValue,
        )

        from sugar_lift_py_tests.outcome import Complete

        return self.value.desugar(ctx).and_then(
            lambda value: Complete(
                AuthenticatedExceptionTypeValue(
                    value, self.identity, self.mro, self.class_value
                )
            )
        )
