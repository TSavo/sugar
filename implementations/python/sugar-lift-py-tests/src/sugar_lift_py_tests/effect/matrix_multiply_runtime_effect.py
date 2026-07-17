from __future__ import annotations

from dataclasses import dataclass

from .runtime_effect import RuntimeEffect, runtime_effect_evidence


@dataclass(frozen=True)
class MatrixMultiplyRuntimeEffect(RuntimeEffect):
    """Reflected matrix multiplication selected by a runtime call result."""

    def kind(self) -> type[RuntimeEffect]:
        return MatrixMultiplyRuntimeEffect


def runtime_matrix_multiply(left, right, site):
    from sugar_lift_py_tests.ir import ctor
    from sugar_lift_py_tests.outcome import Incomplete

    operand = ctor(
        "@",
        [
            left.to_term(owner=str(site)),
            right.to_term(owner=str(site)),
        ],
    )
    return Incomplete(
        MatrixMultiplyRuntimeEffect(
            "matrix multiplication depends on the opaque right operand's "
            f"runtime __rmatmul__ dispatch; site={site}",
            **runtime_effect_evidence("py.matrix_multiply", operand, site),
        )
    )
