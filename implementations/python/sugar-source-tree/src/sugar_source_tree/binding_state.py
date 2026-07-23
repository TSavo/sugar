from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Callable, TypeAlias

from .binding_provenance import (
    BindingCoordinateV1,
    BindingEntryV1 as SealedBindingEntryV1,
    BindingProvenanceGap,
    BindingStateV1 as SealedBindingStateV1,
    BoundBindingStateV1,
    ConstructedValueTestimonyV1,
    GuardedBindingStateV1,
    UnboundBindingStateV1,
)

if TYPE_CHECKING:
    from sugar_source_tree.fragment import SourceFragment
    from sugar_source_tree.nodes import Node


@dataclass(frozen=True)
class UnboundBinding:
    name: str
    cause: SourceFragment


@dataclass(frozen=True)
class BranchResultSlot:
    slot_id: str


def branch_result_slot(test: Node) -> BranchResultSlot:
    memento = test.fragment.seal()
    address = f"{memento.source_cid}@{memento.start}:{memento.end}#{memento.cid}"
    return BranchResultSlot(f"branch-result:{address}")


@dataclass(frozen=True)
class GuardedBinding:
    slot: BranchResultSlot
    when_true: BindingState
    when_false: BindingState


BindingState: TypeAlias = "Node | UnboundBinding | GuardedBinding"


class RuntimeBindingEntryGap(BindingProvenanceGap):
    """A live binding cannot project into the authenticated sealed wire."""


@dataclass(frozen=True)
class BindingEntryV1:
    """The sole runtime temporal binding carrier.

    The live ``state`` is what substitution consumes.  ``sealed_state`` is its
    pure-data projection; no live Node handle enters ``wire()``.
    """

    coordinate: BindingCoordinateV1
    state: BindingState
    sealed_state: SealedBindingStateV1 | None

    @property
    def constructed_value_testimony(self) -> ConstructedValueTestimonyV1 | None:
        if isinstance(self.sealed_state, BoundBindingStateV1):
            return self.sealed_state.testimony
        return None

    def with_testimony(
        self, testimony: ConstructedValueTestimonyV1
    ) -> "BindingEntryV1":
        return replace(self, sealed_state=BoundBindingStateV1(testimony))

    def wire(self) -> dict[str, Any]:
        if self.sealed_state is None:
            raise RuntimeBindingEntryGap(
                "runtime binding state has no authenticated sealed projection"
            )
        if (
            isinstance(self.sealed_state, BoundBindingStateV1)
            and self.sealed_state.testimony is None
        ):
            raise RuntimeBindingEntryGap(
                "constructed-value testimony unavailable"
            )
        # Decode the projection immediately: this authenticates coordinate and
        # testimony CIDs by h=h(p), rather than trusting an in-memory dataclass.
        return SealedBindingEntryV1.decode(
            SealedBindingEntryV1(self.coordinate, self.sealed_state).wire()
        ).wire()


BindingMap: TypeAlias = dict[object, BindingEntryV1 | object]


class RuntimeBindingEntryFactoryV1:
    """The one function-scope minter for runtime binding occurrences."""

    def __init__(self, scope_owner_cid: str) -> None:
        self.scope_owner_cid = scope_owner_cid
        self._ordinal = 0

    def mint_entry(
        self,
        *,
        binding_site: SourceFragment,
        projection_path: tuple[str | int, ...],
        state: BindingState,
    ) -> BindingEntryV1:
        ordinal = self._ordinal
        self._ordinal += 1
        return mint_runtime_binding_entry_v1(
            scope_owner_cid=self.scope_owner_cid,
            binding_site=binding_site,
            projection_path=("occurrence", ordinal, *projection_path),
            state=state,
        )


def mint_runtime_binding_entry_v1(
    *,
    scope_owner_cid: str,
    binding_site: SourceFragment,
    projection_path: tuple[str | int, ...],
    state: BindingState,
) -> BindingEntryV1:
    """Mint one occurrence coordinate and keep its live state beside it."""
    coordinate = BindingCoordinateV1.mint(
        scope_owner_cid, binding_site, projection_path
    )
    if _is_node(state):
        sealed_state: SealedBindingStateV1 | None = BoundBindingStateV1(None)
    elif isinstance(state, UnboundBinding):
        sealed_state = UnboundBindingStateV1(state.cause.seal().cid)
    elif isinstance(state, GuardedBinding):
        # Guard alternatives acquire state CIDs only after their projected
        # entries are sealed.  Until then the runtime entry remains loud.
        sealed_state = None
    else:
        raise RuntimeBindingEntryGap(
            f"unknown runtime binding state {type(state).__name__}"
        )
    return BindingEntryV1(coordinate, state, sealed_state)


def _is_node(value: object) -> bool:
    from sugar_source_tree.nodes import Node

    return isinstance(value, Node)


def unwrap_binding_state(value: BindingEntryV1 | BindingState) -> BindingState:
    return value.state if isinstance(value, BindingEntryV1) else value


def binding_state_read_node(
    state: BindingEntryV1 | BindingState,
    *,
    make_read: Callable[[UnboundBinding | GuardedBinding], Node],
) -> Node:
    """Project binding availability into the tree's ordinary Node currency.

    Binding-state witnesses are deliberately not AST nodes.  A consumer that
    reads a binding must project an unbound/guarded state into the explicit
    read node owned by the read site before placing it in a shadow child slot.
    """
    from sugar_source_tree.nodes import Node

    state = unwrap_binding_state(state)
    if isinstance(state, Node):
        return state
    if isinstance(state, (UnboundBinding, GuardedBinding)):
        return make_read(state)
    raise TypeError(type(state))


def join_binding_state(
    *,
    slot: BranchResultSlot,
    when_true: BindingState,
    when_false: BindingState,
    make_ifexp,
) -> BindingState:
    from sugar_source_tree.nodes import Node

    when_true = unwrap_binding_state(when_true)
    when_false = unwrap_binding_state(when_false)
    if when_true is when_false or when_true == when_false:
        return when_true
    if isinstance(when_true, Node) and isinstance(when_false, Node):
        return make_ifexp(slot, when_true, when_false)
    if isinstance(when_true, UnboundBinding) and isinstance(when_false, UnboundBinding):
        return UnboundBinding(name=when_true.name, cause=when_true.cause)
    return GuardedBinding(slot=slot, when_true=when_true, when_false=when_false)
