from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sugar_lift_py_tests.effect import (
    SetMethodRuntimeEffect,
    runtime_effect_evidence,
)
from sugar_lift_py_tests.ir import Term, ctor

from .floor_value import FloorValue
from .term_value import TermValue


@dataclass(frozen=True)
class SetLiteralValue(FloorValue):
    """A structural Python set literal term with deterministic support order."""

    items: tuple[Term, ...]

    def contribution(self):
        # Typed non-FOL support carrier: absorbed in a block record.
        return ()

    def to_term(self, *, owner: str) -> Term:
        del owner
        return ctor("python:set", list(self.items))

    def call_method_with(self, operation: Any, ctx: object) -> Any:
        del ctx
        if operation.name == "__len__" and not operation.arguments:
            from sugar_lift_py_tests.outcome import Complete

            # Bare folded count; BuiltinCallSugar wrap re-attaches call:len.
            return Complete(TermValue(len(self.items)))
        return _call_method_effect(
            site=operation,
            observed=f"SetLiteralValue.{operation.name}",
        )

    def contains_with(self, operation: Any, ctx: object) -> Any:
        return operation.contains_set(self, ctx)


def _call_method_effect(
    *,
    site,
    observed: str,
):
    from sugar_lift_py_tests.outcome import Incomplete

    return Incomplete(
        SetMethodRuntimeEffect(
            "set builtin method runtime boundary: "
            f"{observed} has no reduced floor semantics in this tranche. "
            "Python set method results can expose runtime mutation and "
            "iteration-order semantics; keep as typed red until a narrower "
            f"vendor-cited reduction owns the shape. blame={site}",
            **runtime_effect_evidence("py.call_method", observed, site),
        )
    )
