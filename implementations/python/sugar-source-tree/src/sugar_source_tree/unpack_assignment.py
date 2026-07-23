"""Typed identity and structural paths for one destructuring occurrence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TypeAlias


@dataclass(frozen=True)
class Position:
    index: int

    def __post_init__(self) -> None:
        if type(self.index) is not int or self.index < 0:
            raise ValueError("unpack Position requires a nonnegative integer")


UnpackPathStep: TypeAlias = Position
UnpackPath: TypeAlias = tuple[UnpackPathStep, ...]


@dataclass(frozen=True)
class UnpackNamePattern:
    name: str


@dataclass(frozen=True)
class UnpackSequencePattern:
    kind: str
    elements: tuple["UnpackPattern", ...]

    def __post_init__(self) -> None:
        if self.kind not in {"tuple", "list"} or not self.elements:
            raise ValueError("unpack sequence pattern requires tuple/list elements")


UnpackPattern: TypeAlias = UnpackNamePattern | UnpackSequencePattern


@dataclass(frozen=True)
class UnpackAssignmentSlot:
    slot_id: str


def _pattern_json(pattern: UnpackPattern):
    if isinstance(pattern, UnpackNamePattern):
        return {"name": pattern.name}
    return {
        "kind": pattern.kind,
        "elements": [_pattern_json(element) for element in pattern.elements],
    }


def unpack_assignment_slot(fragment, pattern: UnpackSequencePattern):
    """Mint one address from authenticated source plus canonical pattern."""
    memento = fragment.seal()
    canonical = json.dumps(
        _pattern_json(pattern), sort_keys=True, separators=(",", ":")
    )
    pattern_cid = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    address = f"{memento.source_cid}@{memento.start}:{memento.end}#{memento.cid}"
    return UnpackAssignmentSlot(f"unpack-assignment:{address}:{pattern_cid}")


def pattern_bindings(
    pattern: UnpackSequencePattern, prefix: UnpackPath = ()
) -> tuple[tuple[str, UnpackPath], ...]:
    bindings: list[tuple[str, UnpackPath]] = []
    for index, element in enumerate(pattern.elements):
        path = (*prefix, Position(index))
        if isinstance(element, UnpackNamePattern):
            bindings.append((element.name, path))
        else:
            bindings.extend(pattern_bindings(element, path))
    return tuple(bindings)


def path_in_pattern(pattern: UnpackSequencePattern, path: UnpackPath) -> bool:
    current: UnpackPattern = pattern
    for step in path:
        if not isinstance(current, UnpackSequencePattern):
            return False
        if step.index >= len(current.elements):
            return False
        current = current.elements[step.index]
    return isinstance(current, UnpackNamePattern)
