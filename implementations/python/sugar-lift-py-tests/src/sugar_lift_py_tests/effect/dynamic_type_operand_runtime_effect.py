from dataclasses import dataclass

from .runtime_effect import RuntimeEffect


@dataclass(frozen=True)
class DynamicTypeOperandRuntimeEffect(RuntimeEffect):
    """Python must resolve a non-citable ``isinstance`` type operand."""

    def kind(self) -> type[RuntimeEffect]:
        return DynamicTypeOperandRuntimeEffect
