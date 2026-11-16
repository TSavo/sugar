from __future__ import annotations

from dataclasses import dataclass

from .class_value import ClassValue


@dataclass(frozen=True)
class LocalExceptionClassValue(ClassValue):
    """Source-proven local class with exact exception ancestry."""
