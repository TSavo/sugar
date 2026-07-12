from dataclasses import dataclass

from .runtime_effect import RuntimeEffect


@dataclass(frozen=True)
class CallResultContextManagerRuntimeEffect(RuntimeEffect):
    """Python must execute an unresolved call before applying the with protocol."""
