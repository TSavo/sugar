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

``Provider.parse`` has two outcomes: a root ``ProviderHandle``, or
``ProviderRefused`` — the OTHER two-arm law, sitting beside
``MembranePanic`` (panic.py). They name different failures. A
``MembranePanic`` is OUR gap: a shape the provider produced has no
membrane class. ``ProviderRefused`` is the PROVIDER's own gap: the raw
text was not valid input for it at all — a syntax error, an unparseable
token, a null byte, whatever that backend's parser refuses on. Every
adapter must raise ``ProviderRefused`` — never its native library
exception (``SyntaxError``, ``libcst.ParserSyntaxError``, ...) — so that
no caller above ``backend.py`` ever needs to know, or guess, which parsing
library is behind the membrane today.
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


class ProviderRefused(Exception):
    """The provider refused the source unit: not valid input for it.

    Distinct from ``MembranePanic`` (panic.py), which is a membrane MISSING
    — a shape the provider DID produce but we have no class for. This is
    the provider declining to produce a tree at all: a syntax error, a
    tokenizer error, a null byte, an encoding it will not accept. Every
    adapter's ``parse`` raises exactly this on such input, carrying its own
    provider name, the file, and the provider's own reason — never letting
    its native exception type (``SyntaxError``, ``libcst.ParserSyntaxError``,
    or whatever the next provider throws) escape past ``backend.py``.

    Never caught to continue silently: a refusal is a recorded outcome
    (corpus.py records it as a failure row), not a substitute for success
    and never a bare ``None``.
    """

    def __init__(self, provider: str, file: str, reason: str) -> None:
        super().__init__(provider, file, reason)
        self.provider = provider
        self.file = file
        self.reason = reason

    def __str__(self) -> str:  # pragma: no cover - formatting only
        return f"PROVIDER REFUSED [{self.provider}] {self.file}: {self.reason}"


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
    """A parsing backend. The whole contract: source text in, root handle out.

    Two outcomes: a root ``ProviderHandle``, or ``ProviderRefused`` raised
    when ``unit.source`` is not valid input for this backend. Never its
    native library exception.
    """

    name: str = ""

    def parse(self, unit: SourceUnit) -> ProviderHandle:
        raise NotImplementedError
