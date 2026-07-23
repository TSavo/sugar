from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_source_tree.binding_state import BranchResultSlot


@dataclass(frozen=True)
class UnboundProjection:
    name: str
    cause: object


@dataclass(frozen=True)
class GuardedProjection:
    slot: BranchResultSlot
    when_true: BindingProjection
    when_false: BindingProjection


BindingProjection: TypeAlias = "Sugar | UnboundProjection | GuardedProjection"
