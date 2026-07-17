from __future__ import annotations

from dataclasses import dataclass

from .runtime_effect import RuntimeEffect, runtime_effect_witness


@dataclass(frozen=True)
class DivideRuntimeEffect(RuntimeEffect):
    """Division whose Python data-model dispatch exists only at runtime."""

    def kind(self) -> type[RuntimeEffect]:
        return DivideRuntimeEffect


def runtime_divide(left, right, site):
    """Build one authenticated boundary for runtime true-division dispatch."""
    from sugar_lift_py_tests.ir import ctor
    from sugar_lift_py_tests.outcome import Incomplete

    operand = ctor(
        "/",
        [
            left.to_term(owner=str(site)),
            right.to_term(owner=str(site)),
        ],
    )
    return Incomplete(
        DivideRuntimeEffect(
            "division depends on runtime __truediv__/__rtruediv__ dispatch; "
            f"left={type(left).__name__} right={type(right).__name__} site={site}",
            witness=runtime_effect_witness("py.divide", operand, site),
        )
    )
