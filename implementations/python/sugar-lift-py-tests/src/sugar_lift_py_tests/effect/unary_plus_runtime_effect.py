from __future__ import annotations

from dataclasses import dataclass

from .runtime_effect import RuntimeEffect, runtime_effect_evidence


@dataclass(frozen=True)
class UnaryPlusRuntimeEffect(RuntimeEffect):
    """Unary-plus dispatch whose call-result type exists only at runtime."""

    def kind(self) -> type[RuntimeEffect]:
        return UnaryPlusRuntimeEffect


def runtime_unary_plus(operand, site):
    from sugar_lift_py_tests.outcome import Incomplete

    return Incomplete(
        UnaryPlusRuntimeEffect(
            "unary plus depends on the opaque call result's __pos__ dispatch; "
            f"site={site}",
            **runtime_effect_evidence("py.unary_plus", operand, site),
        )
    )
