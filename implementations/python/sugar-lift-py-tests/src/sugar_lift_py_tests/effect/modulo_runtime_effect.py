from __future__ import annotations

from dataclasses import dataclass

from .runtime_effect import RuntimeEffect, runtime_effect_evidence


@dataclass(frozen=True)
class ModuloRuntimeEffect(RuntimeEffect):
    """Modulo whose Python data-model dispatch exists only at runtime."""

    def kind(self) -> type[RuntimeEffect]:
        return ModuloRuntimeEffect


def runtime_modulo(left, right, site):
    """Build one authenticated boundary for runtime modulo dispatch."""
    from sugar_lift_py_tests.ir import ctor
    from sugar_lift_py_tests.outcome import Incomplete

    operand = ctor(
        "%",
        [
            left.to_term(owner=str(site)),
            right.to_term(owner=str(site)),
        ],
    )
    return Incomplete(
        ModuloRuntimeEffect(
            "modulo depends on runtime __mod__/__rmod__ dispatch; "
            f"left={type(left).__name__} right={type(right).__name__} site={site}",
            **runtime_effect_evidence("py.modulo", operand, site),
        )
    )
