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
    Leaf,
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


class OccurrenceShadowNode(ShadowNode):
    """A copy of a node that denotes ONE dynamic evaluation of its source.

    A concrete loop dissolves into one copy of its body per iteration, and a
    comprehension into one copy of its element per member. Those copies borrow
    the same span, so a site key (``file [start, end) node``) cannot tell the
    evaluations apart and an opaque atom keyed on it would name one unknown for
    all of them. ``occurrence_tags`` (outermost first) are the iteration
    segments this copy stands for; the reducer enters them while it reduces the
    copy (``sugar_lift_py_tests.occurrence``), so each evaluation keys its own
    atoms.
    """

    __slots__ = ("occurrence_tags",)

    def __init__(
        self,
        kind: str,
        span: Span,
        slots: Tuple[Tuple[str, Slot], ...],
        occurrence_tags: Tuple[str, ...],
    ) -> None:
        super().__init__(kind, span, slots)
        self.occurrence_tags = tuple(occurrence_tags)


def occurrence_tags_of(node: Node) -> Tuple[str, ...]:
    """The iteration segments a node copy stands for (empty for source nodes)."""
    return getattr(getattr(node, "ref", None), "occurrence_tags", ())


def as_occurrence(origin: Node, segment: str) -> Node:
    """A fresh copy of ``origin`` that is evaluation ``segment`` of it.

    Same kind, span and children; a distinct construction coordinate (so its
    sugar is its own) carrying ``segment`` outside any segments ``origin``
    already stood for (an inner loop's iteration inside this one).
    """
    desc = origin.ref.describe()  # type: ignore[attr-defined]
    shadow = OccurrenceShadowNode(
        desc.kind,
        desc.raw_span or origin.span,
        tuple(desc.slots),
        (segment, *occurrence_tags_of(origin)),
    )
    copy = materialize(origin.unit, shadow, origin.reporter, origin.control_context)
    _retain_call_row(origin, copy)
    return copy


def _retain_call_row(origin: Node, copy: Node) -> None:
    """An evaluation of a source call is still that call (#7673).

    The copy is a fresh backend identity over the origin's span and kind, so
    it joins the origin's published enrollment decision by occurrence; its
    producer-owned lexical row is keyed by identity and must ride along, as
    ``Call.substitute`` carries it for a rewrite.  Only the copied node itself
    gets a new identity -- its children are the origin's own handles.
    """
    from .nodes import Call, LexicalCallEnrolledV1

    if isinstance(origin, Call) and isinstance(
        origin.unit.lexical_call_enrollment(origin), LexicalCallEnrolledV1
    ):
        origin.unit.retain_lexical_call_row(origin, copy)


def iteration_segment(loop: Node, index: int) -> str:
    """Iteration ``index`` of the loop (or comprehension) node ``loop``."""
    span = loop.span
    return f"loop[{span.start},{span.end})#{index}"


def _handle_of(node: Node) -> BackendNode:
    """The backend handle behind a materialized node — source- or shadow-backed.
    Rewriting a parent points its child slots at these, never at Node objects."""
    return node.ref  # type: ignore[attr-defined]


def _child_slot(replacement: object) -> Slot:
    """The child slot holding ``replacement``: a Node, None (an absent
    optional child), or a tuple of Nodes."""
    if isinstance(replacement, Node):
        return Child(_handle_of(replacement))
    if replacement is None:
        return MaybeChild(None)
    if isinstance(replacement, tuple):
        return Children(tuple(_handle_of(n) for n in replacement))
    return MaybeChild(_handle_of(replacement))


def rewrite(origin: Node, **children: object) -> Node:
    """Produce a shadow-backed rewrite of ``origin`` with some child slots
    replaced, keeping its kind, span and every unchanged slot.

    ``children`` names the field(s) to replace; each value is the new child
    Node, an optional child Node/None, or a tuple of child Nodes. Everything
    not named is carried through from the origin's own describe(). The result
    borrows the origin's span, so its memento still addresses the source the
    rewrite stands for.
    """
    return rewrite_with_leaves(origin, {}, **children)


def rewrite_with_leaves(origin: Node, leaves: dict, /, **children: object) -> Node:
    """``rewrite``, also setting the leaf slots ``leaves`` names (a leaf of
    that name is replaced, a new one appended).  A statement carries what its
    substitution decided this way -- ``a, b = f()`` its evaluation key -- and
    stays the same evaluation of the same source occurrence.  A child slot
    ``children`` names that the origin does not have is appended the same
    way: ``a = o.x = v`` carries each store target's own statement
    (``Assign.stores``)."""
    desc = origin.ref.describe()  # type: ignore[attr-defined]
    new_slots: list[Tuple[str, Slot]] = []
    present = set()
    for name, slot in desc.slots:
        present.add(name)
        if name in leaves:
            continue
        if name not in children:
            new_slots.append((name, slot))
            continue
        new_slots.append((name, _child_slot(children[name])))
    new_slots.extend(
        (name, _child_slot(replacement))
        for name, replacement in children.items()
        if name not in present and name not in leaves
    )
    new_slots.extend((name, Leaf(value)) for name, value in leaves.items())
    tags = occurrence_tags_of(origin)
    if tags:
        # A rewrite of one evaluation is still that evaluation.
        shadow = OccurrenceShadowNode(
            desc.kind, desc.raw_span or origin.span, tuple(new_slots), tags
        )
    else:
        shadow = ShadowNode(desc.kind, desc.raw_span or origin.span, tuple(new_slots))
    # Same materialize door as source backends: shadow ref is another memoized
    # backend identity; field data is interned on the unit, shells are free.
    return materialize(origin.unit, shadow, origin.reporter, origin.control_context)
