from __future__ import annotations

from dataclasses import dataclass

from .runtime_effect import RuntimeEffect, runtime_effect_evidence


@dataclass(frozen=True)
class BitwiseXorRuntimeEffect(RuntimeEffect):
    """Bitwise xor whose call-result dispatch exists only at runtime."""

    def kind(self) -> type[RuntimeEffect]:
        return BitwiseXorRuntimeEffect


def runtime_bitwise_xor(left, right, site):
    from sugar_lift_py_tests.ir import ctor
    from sugar_lift_py_tests.outcome import Incomplete

    operand = ctor(
        "^",
        [
            left.to_term(owner=str(site)),
            right.to_term(owner=str(site)),
        ],
    )
    return Incomplete(
        BitwiseXorRuntimeEffect(
            "bitwise xor depends on the opaque call result's "
            f"__xor__/__rxor__ dispatch; site={site}",
            **runtime_effect_evidence("py.bitwise_xor", operand, site),
        )
    )
