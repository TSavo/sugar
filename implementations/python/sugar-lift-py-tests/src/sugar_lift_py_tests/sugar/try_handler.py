from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.floor import SymbolicValue
from sugar_lift_py_tests.ir import ctor, str_const
from sugar_lift_py_tests.sugar_body import SugarBody
from sugar_lift_py_tests.temporal import bind_temporal


@dataclass(frozen=True)
class TryHandler:
    exception_names: tuple[str, ...] | None
    bound_name: str | None
    body: SugarBody
    site: object = dataclass_field(compare=False)

    def matches(self, effect: RaiseEffect) -> bool:
        if self.exception_names is None:
            return True
        if not self.exception_names:
            return False
        if (
            "BaseException" in self.exception_names
            or "Exception" in self.exception_names
        ):
            return True
        return effect.exception_name in self.exception_names

    def reduce(self, ctx, effect: RaiseEffect):
        if self.bound_name is None:
            return self.body.reduce(ctx)
        exception_term = ctor(
            "py.exception",
            [str_const(effect.exception_name or "unknown")],
        )
        handler_ctx = bind_temporal(
            ctx,
            self.bound_name,
            SymbolicValue(exception_term),
            owner="TryHandler",
            blame=self.site,
        )
        return self.body.reduce(handler_ctx)
