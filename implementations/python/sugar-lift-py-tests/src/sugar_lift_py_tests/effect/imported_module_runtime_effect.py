from dataclasses import dataclass

from .runtime_effect import RuntimeEffect


@dataclass(frozen=True)
class ImportedModuleRuntimeEffect(RuntimeEffect):
    """An imported module's dynamic runtime content must be evaluated by Python."""

