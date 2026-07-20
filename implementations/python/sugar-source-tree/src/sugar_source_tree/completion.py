"""PROBE (#5940): completion — ask the NODE for its sugar.

The inversion under test
------------------------

Today recognition is an open-world search: a factory holds a catalog of
claims, scans every one, and asks each ``owns(site)``. This module probes
T's inversion: possibility is a property of the grammar class, so the
question is closed-world and the NODE should answer it. ``node.sugar()``
dispatches on ``type(node)``; refinement inside a closed family reads the
node's own typed fields.

What ``owns`` becomes here
--------------------------

* For a node class with ONE completion (``If``), ``owns`` is DELETED.
  The declaration ``completes = If`` is the whole of the old predicate,
  and a second sole completion for the same class is a REGISTRATION-TIME
  panic — the ambiguity arm dies at import, before any site exists.
* For a closed family (``Call``), ``owns`` shrinks to ``refines``: the
  family's discrimination over the node's own typed fields. Members of
  one family must be disjoint; two refining at once is still a panic,
  but it can now arise ONLY inside a declared family — never between
  strangers — and the panic names the family.

Registration stays pluggable: a language kit declares completion classes
(``completes = <NodeClass>``) and ``__init_subclass__`` registers them.
No central dispatcher is ever edited.

Two arms, as everywhere: a completion class, or a loud panic. A node
whose class has no completion, or whose family does not cover its field
shape, panics ``CompletionGap`` — "I know what I am and nothing
completes me." Never silence, never a bare ``None``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Dict, List, Tuple, Type

from .panic import SourceTreePanic

if TYPE_CHECKING:  # pragma: no cover
    from .nodes import Node


class CompletionGap(SourceTreePanic):
    """The node knows what it is and nothing completes it. The gap arm,
    relocated from the factory scan onto the ask itself."""

    _LABEL = "COMPLETION GAP"


class CompletionAmbiguous(SourceTreePanic):
    """More than one completion answered. Between sole completions this is
    impossible by construction (registration panics first); inside a family
    it means the family's refinement is not a partition of the node's field
    shapes — a defect in the family, named as such."""

    _LABEL = "COMPLETION AMBIGUOUS"


#: node class -> registered completion classes, in registration order.
#: Registration order is NOT precedence: resolution requires exactly one
#: refining member, so order never picks a winner.
_REGISTRY: Dict[type, List[Type["Completion"]]] = {}


class Completion:
    """One completion of a node class. Subclass and declare ``completes``.

    ``sole = True`` (default): this class is the ONLY completion of its
    node class. ``refines`` is never consulted; a second registration for
    the same node class panics at import.

    ``sole = False``: this class is a member of a closed family sharing
    one node class. ``refines(node)`` reads the node's own typed fields
    to claim its partition cell. Family members must be pairwise
    disjoint and should jointly cover the class — a cell nobody claims
    is the gap arm, at the ask.
    """

    completes: ClassVar[type]
    sole: ClassVar[bool] = True

    def __init_subclass__(cls, **kw: object) -> None:
        super().__init_subclass__(**kw)
        completes = cls.__dict__.get("completes")
        if completes is None:
            return  # abstract intermediate; concrete classes declare it
        existing = _REGISTRY.setdefault(completes, [])
        if existing and (cls.sole or any(e.sole for e in existing)):
            raise CompletionAmbiguous(
                owner="completion.Completion.__init_subclass__",
                observed=(
                    f"{cls.__name__} registers for {completes.__name__}, "
                    f"already completed by "
                    f"[{', '.join(e.__name__ for e in existing)}] with a "
                    f"sole completion involved"
                ),
                requested="one sole completion, or an all-family set",
                fix=(
                    "a node class has either exactly one completion or one "
                    "closed family (every member sole = False). Two sole "
                    "completions cannot coexist — this panic fires at import, "
                    "before any site exists: the ambiguity arm dies at "
                    "registration, not at resolution."
                ),
            )
        existing.append(cls)

    @classmethod
    def refines(cls, node: "Node") -> bool:
        """Family discrimination over the node's own typed fields. Sole
        completions never reach here. Returning True/False is an ANSWER;
        a member that cannot answer must panic, never return False."""
        raise NotImplementedError(f"{cls.__name__} is sole; refines is never asked")


def resolve_completion(node: "Node") -> Type[Completion]:
    """THE two-arm match, from the node's side: exactly one completion,
    or a loud panic. Called as ``node.sugar()``."""
    cls = type(node)
    entries = _REGISTRY.get(cls, [])
    if not entries:
        raise CompletionGap(
            owner="completion.resolve_completion",
            observed=(
                f"{cls.__name__} at [{node.span.start},{node.span.end}) in "
                f"{node.unit.filename} — I know what I am and nothing "
                f"completes me"
            ),
            requested="a Completion declaring completes = " + cls.__name__,
            fix=(
                "declare the completion (sole, or a family member) for this "
                "grammar class. Never widen a neighbor to swallow it."
            ),
        )
    if len(entries) == 1 and entries[0].sole:
        return entries[0]
    matches = [c for c in entries if c.refines(node)]
    if len(matches) == 1:
        return matches[0]
    family = ", ".join(e.__name__ for e in entries)
    if not matches:
        raise CompletionGap(
            owner="completion.resolve_completion",
            observed=(
                f"{cls.__name__} at [{node.span.start},{node.span.end}) in "
                f"{node.unit.filename} — family [{family}] covers no cell "
                f"for this field shape"
            ),
            requested="exactly one refining family member",
            fix=(
                "extend the family with the member for this field shape, or "
                "extend an existing member's cell — deliberately, never by "
                "default."
            ),
        )
    raise CompletionAmbiguous(
        owner="completion.resolve_completion",
        observed=(
            f"{cls.__name__} at [{node.span.start},{node.span.end}) in "
            f"{node.unit.filename} — "
            f"[{', '.join(m.__name__ for m in matches)}] all refine within "
            f"family [{family}]"
        ),
        requested="a partition: exactly one refining member",
        fix=(
            "the family's refinement is not disjoint over this node's field "
            "shape. Make the cells disjoint; there is no precedence and "
            "picking the first is not available — that would be a third arm."
        ),
    )


def registered() -> Dict[type, Tuple[Type[Completion], ...]]:
    """Read-only view for tests and diagnostics. Not a resolution."""
    return {k: tuple(v) for k, v in _REGISTRY.items()}
