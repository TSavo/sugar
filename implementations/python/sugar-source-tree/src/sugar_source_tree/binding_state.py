from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, TypeAlias

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
BindingMap: TypeAlias = dict[str, BindingState]


def binding_state_read_node(
    state: BindingState,
    *,
    make_read: Callable[[UnboundBinding | GuardedBinding], Node],
) -> Node:
    """Project binding availability into the tree's ordinary Node currency.

    Binding-state witnesses are deliberately not AST nodes.  A consumer that
    reads a binding must project an unbound/guarded state into the explicit
    read node owned by the read site before placing it in a shadow child slot.
    """
    from sugar_source_tree.nodes import Node

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

    if when_true is when_false or when_true == when_false:
        return when_true
    if isinstance(when_true, Node) and isinstance(when_false, Node):
        return make_ifexp(slot, when_true, when_false)
    if isinstance(when_true, UnboundBinding) and isinstance(when_false, UnboundBinding):
        return UnboundBinding(name=when_true.name, cause=when_true.cause)
    return GuardedBinding(slot=slot, when_true=when_true, when_false=when_false)
