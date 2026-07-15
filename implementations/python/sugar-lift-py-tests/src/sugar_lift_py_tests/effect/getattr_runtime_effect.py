from dataclasses import dataclass

from .runtime_effect import RuntimeEffect


@dataclass(frozen=True)
class GetattrRuntimeEffect(RuntimeEffect):
    """Python must choose a dynamic attribute name or resolve an opaque receiver."""

    def kind(self) -> type[RuntimeEffect]:
        return GetattrRuntimeEffect
