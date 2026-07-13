from dataclasses import dataclass

from .runtime_effect import RuntimeEffect


@dataclass(frozen=True)
class CallResultTypeRuntimeEffect(RuntimeEffect):
    """Python must execute an unresolved call before its result can name a type."""
