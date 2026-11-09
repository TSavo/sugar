from dataclasses import dataclass

from .runtime_effect import RuntimeEffect


@dataclass(frozen=True)
class DynamicTypeOperandRuntimeEffect(RuntimeEffect):
    """Python must resolve a non-citable ``isinstance`` type operand."""

    def kind(self) -> type[RuntimeEffect]:
        return DynamicTypeOperandRuntimeEffect

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor

        # Cite the already-authenticated operation (typically adt.is_python_type
        # of a value and a non-citable type operand). Do not invent a type
        # identity or include the reason prose.
        return ctor(
            "python:dynamic-type-operand",
            [self.witness.operation],
            symbol_kind="coordinate",
        )
