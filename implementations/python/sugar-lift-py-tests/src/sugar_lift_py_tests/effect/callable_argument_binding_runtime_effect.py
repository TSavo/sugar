from __future__ import annotations

from dataclasses import dataclass

from .runtime_effect import RuntimeEffect, runtime_effect_evidence


@dataclass(frozen=True)
class CallableArgumentBindingRuntimeEffect(RuntimeEffect):
    """Keyword binding whose expansion keys exist only at runtime."""

    def kind(self) -> type[RuntimeEffect]:
        return CallableArgumentBindingRuntimeEffect


def runtime_callable_argument_binding(operand, site):
    from sugar_lift_py_tests.outcome import Incomplete

    return Incomplete(
        CallableArgumentBindingRuntimeEffect(
            "call argument binding depends on the runtime keys of an opaque "
            f"**mapping expansion; site={site}",
            **runtime_effect_evidence(
                "py.callable_argument_binding",
                operand,
                site,
            ),
        )
    )
