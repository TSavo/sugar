from __future__ import annotations

from dataclasses import dataclass

from .runtime_effect import RuntimeEffect


@dataclass(frozen=True)
class SequenceRepetitionRuntimeEffect(RuntimeEffect):
    """Sequence repetition that cannot be represented by a finite concrete floor."""
