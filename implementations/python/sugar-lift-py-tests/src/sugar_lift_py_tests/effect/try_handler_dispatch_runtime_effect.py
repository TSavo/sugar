from dataclasses import dataclass

from .runtime_effect import RuntimeEffect


@dataclass(frozen=True)
class TryHandlerDispatchRuntimeEffect(RuntimeEffect):
    """Python must evaluate an exception-handler expression before dispatch."""
