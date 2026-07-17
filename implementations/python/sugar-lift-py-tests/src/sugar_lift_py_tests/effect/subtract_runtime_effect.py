from __future__ import annotations

from dataclasses import dataclass

from .runtime_effect import RuntimeEffect, runtime_effect_evidence


@dataclass(frozen=True)
class SubtractRuntimeEffect(RuntimeEffect):
    """Subtraction whose Python data-model dispatch exists only at runtime."""

    def kind(self) -> type[RuntimeEffect]:
        return SubtractRuntimeEffect


def runtime_subtract(left, right, site):
    """Build one authenticated boundary for runtime subtraction dispatch."""
    from sugar_lift_py_tests.ir import ctor
    from sugar_lift_py_tests.outcome import Incomplete

    operand = ctor(
        "-",
        [
            left.to_term(owner=str(site)),
            right.to_term(owner=str(site)),
        ],
    )
    return Incomplete(
        SubtractRuntimeEffect(
            "subtraction depends on runtime __sub__/__rsub__ dispatch; "
            f"left={type(left).__name__} right={type(right).__name__} site={site}",
            **runtime_effect_evidence("py.subtract", operand, site),
        )
    )
