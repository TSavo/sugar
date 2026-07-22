from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeAlias

if TYPE_CHECKING:
    from sugar_source_tree.fragment import SourceFragment
    from sugar_source_tree.nodes import Node


@dataclass(frozen=True)
class UnboundBinding:
    name: str
    cause: SourceFragment


@dataclass(frozen=True)
class GuardedBinding:
    test: Node
    when_true: BindingState
    when_false: BindingState


BindingState: TypeAlias = "Node | UnboundBinding | GuardedBinding"
BindingMap: TypeAlias = dict[str, BindingState]


def join_binding_state(
    *,
    test: Node,
    when_true: BindingState,
    when_false: BindingState,
    make_ifexp: Callable[[Node, Node, Node], Node],
) -> BindingState:
    from sugar_source_tree.nodes import Node

    if when_true is when_false or when_true == when_false:
        return when_true
    if isinstance(when_true, Node) and isinstance(when_false, Node):
        return make_ifexp(test, when_true, when_false)
    if isinstance(when_true, UnboundBinding) and isinstance(
        when_false, UnboundBinding
    ):
        return UnboundBinding(name=when_true.name, cause=when_true.cause)
    return GuardedBinding(test=test, when_true=when_true, when_false=when_false)
