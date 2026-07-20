"""The provider contract: read-only handles, nothing more.

All a parsing library must supply: ``parse(unit) -> handle``, and per handle
a single ``describe()`` giving its kind, its raw span (already normalized to
OUR codepoint span semantics — see spans.py), optional anchor spans for
kinds the provider cannot position, and its fields as slots.

Handles are ``Typeable``: they can be asked for their membrane type, and a
kind with no membrane class panics as a MISSING. Handles are read-only; the
membrane never writes anything onto them (no stamping) and never hands them
to callers above the adapter.

Nothing above an adapter may name ``ast`` (or any other backend library).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from .nodes import SourceFragment, SourceUnit, Typeable, resolve_kind
from .operators import Operator
from .spans import Span


@dataclass(frozen=True)
class Child:
    """Exactly-one child slot."""

    handle: "ProviderHandle"


@dataclass(frozen=True)
class MaybeChild:
    """Zero-or-one child slot. ``None`` is a structural absence."""

    handle: Optional["ProviderHandle"]


@dataclass(frozen=True)
class Children:
    """Zero-or-more child slot."""

    handles: Tuple["ProviderHandle", ...]


@dataclass(frozen=True)
class Leaf:
    """A non-node value carried on the node (identifier, constant, flag)."""

    value: object


@dataclass(frozen=True)
class OpLeaf:
    """A single operator (see operators.py)."""

    op: Operator


@dataclass(frozen=True)
class OpsLeaf:
    """An operator sequence (Compare)."""

    ops: Tuple[Operator, ...]


Slot = Child | MaybeChild | Children | Leaf | OpLeaf | OpsLeaf


@dataclass(frozen=True)
class Description:
    """Everything the builder needs about one backend node, described once.

    ``raw_span`` is the node's span in OUR semantics, or ``None`` for kinds
    the provider does not position (the builder then takes the envelope of
    child spans and ``anchors``). ``slots`` maps membrane field names to
    slot values, in the membrane class's declared field order.
    """

    kind: str
    raw_span: Optional[Span]
    anchors: Tuple[Span, ...]
    slots: Tuple[Tuple[str, Slot], ...]


class ProviderHandle(Typeable):
    """A read-only handle onto one backend node. Typeable, not Typed."""

    def describe(self) -> Description:
        raise NotImplementedError

    def resolve_type(self) -> type[SourceFragment]:
        """Two arms: the concrete membrane class for this kind, or panic."""
        return resolve_kind(self.describe().kind, observed_at=repr(self))


class Provider:
    """A parsing backend. The whole contract: source text in, root handle out."""

    name: str = ""

    def parse(self, unit: SourceUnit) -> ProviderHandle:
        raise NotImplementedError
