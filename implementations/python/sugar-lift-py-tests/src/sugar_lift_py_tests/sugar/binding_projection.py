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


@dataclass(frozen=True)
class LoopGuardedCompletedFace:
    completion_kind: str
    guard_formula: object
    state: BindingProjection
    exit_partition_arity: int | None = None


@dataclass(frozen=True)
class LoopGuardedProjection:
    completed_faces: tuple[LoopGuardedCompletedFace, ...]
    target_cid: str | None = None
    """The authenticated producer OCCURRENCE these faces belong to.

    A partition family is minted over one origin, and this is that origin: two
    loops in one function are two occurrences and share no exclusion. Carrying
    the target CID is what stops a downstream mint from keying on anything
    weaker (a name, a completion kind, a value type) -- the trap the same-type
    partition law exists to refuse.
    """


BindingProjection: TypeAlias = (
    "Sugar | UnboundProjection | GuardedProjection | LoopGuardedProjection"
)
