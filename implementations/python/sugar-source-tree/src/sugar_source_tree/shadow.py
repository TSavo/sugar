"""The shadow backend: a rewritten tree is its own provider.

Every node is a view over a backend that answers ``describe()``. The other
backends (ast, libcst, tree-sitter) answer by parsing source. The SHADOW
backend answers by carrying a *rewritten* node — a node that is not in any
source, produced by substitution.

This is what lets reduction stay in AST-land. Reducing is rewriting: a
source-backed node rewrites to a shadow-backed node (``x`` -> ``1``,
``1 == 1`` -> ``True``), and the result satisfies the exact same Node
interface — ``.fragment``, ``.sugar()``, ``.substitute()`` — indistinguishable
from a parsed node. There is no environment threaded alongside and no
separate value domain: the rewritten tree IS the state.

A ShadowNode is constructed directly with its kind, a borrowed span (the
source extent its value came from — so the memento still content-addresses,
and shared subtrees are shared by CID), and its slots pointing at existing
BackendNode handles (source- or shadow-backed children). It never parses,
never reads source, never names a parser library.
"""

from __future__ import annotations

from typing import Optional, Tuple

from .backend import (
    BackendNode,
    Child,
    Children,
    Description,
    MaybeChild,
    Slot,
    materialize,
)
from .nodes import Node, SourceUnit, resolve_kind
from .spans import Span


class ShadowNode(BackendNode):
    """A backend node that carries a rewritten shape rather than a parsed one.

    Read-only, like every BackendNode: ``describe()`` returns the shape it was
    built with. It is the same currency the parsers produce — the substitution
    layer above cannot tell a shadow child from a source child, and must not.
    """

    __slots__ = ("_kind", "_span", "_slots")

    def __init__(
        self,
        kind: str,
        span: Span,
        slots: Tuple[Tuple[str, Slot], ...],
    ) -> None:
        self._kind = kind
        self._span = span
        self._slots = slots

    def describe(self) -> Description:
        return Description(
            kind=self._kind,
            raw_span=self._span,
            anchors=(),
            slots=self._slots,
        )

    def resolve_type(self):
        # Typeable: our kind -> our node class; a kind with no class panics
        # MISSING exactly as a parsed node would.
        return resolve_kind(self._kind, observed_at="<shadow rewrite>")


def _handle_of(node: Node) -> BackendNode:
    """The backend handle behind a materialized node — source- or shadow-backed.
    Rewriting a parent points its child slots at these, never at Node objects."""
    return node.ref  # type: ignore[attr-defined]


def rewrite(origin: Node, **children: object) -> Node:
    """Produce a shadow-backed rewrite of ``origin`` with some child slots
    replaced, keeping its kind, span and every unchanged slot.

    ``children`` names the field(s) to replace; each value is the new child
    Node, an optional child Node/None, or a tuple of child Nodes. Everything
    not named is carried through from the origin's own describe(). The result
    borrows the origin's span, so its memento still addresses the source the
    rewrite stands for.
    """
    desc = origin.ref.describe()  # type: ignore[attr-defined]
    new_slots: list[Tuple[str, Slot]] = []
    for name, slot in desc.slots:
        if name not in children:
            new_slots.append((name, slot))
            continue
        replacement = children[name]
        if isinstance(replacement, Node):
            new_slots.append((name, Child(_handle_of(replacement))))
        elif replacement is None:
            new_slots.append((name, MaybeChild(None)))
        elif isinstance(replacement, tuple):
            new_slots.append(
                (name, Children(tuple(_handle_of(n) for n in replacement)))
            )
        else:  # an optional single child given as a Node was handled above
            new_slots.append((name, MaybeChild(_handle_of(replacement))))
    shadow = ShadowNode(desc.kind, desc.raw_span or origin.span, tuple(new_slots))
    # Same materialize door as source backends: shadow ref is another memoized
    # backend identity; field data is interned on the unit, shells are free.
    return materialize(
        origin.unit, shadow, origin.reporter, origin.control_context
    )
