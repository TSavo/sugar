"""The typed context-manager contract, and the recognition membrane that issues it.

T's ruling: three contracts wear the one `with` syntax, and production tree code
sees a TYPED CONTRACT, never a vendor spelling. `pytest` is a vendor: the
membrane authenticates community spellings (`pytest.raises(E)`,
`contextlib.suppress(E)`, `tm.assert_produces_warning(W)`) and issues the
general contract; the language implementation (nodes.py) consults the membrane
and never matches names itself.

The exit contracts (the only licenses for temporal dissolution):
- ``NeverSuppresses`` -- exceptional body effect passes through after __exit__.
- ``Suppresses(matcher)`` -- matching effects are consumed (permission).
- ``Expects(matcher)`` -- matching effect is REQUIRED and consumed (obligation).
- ``RuntimeSelected`` -- suppression undecidable statically; stays loud.

Matching rule (pinned): EXACT exception-name match. Subclass matching needs a
static type hierarchy the lift does not hold; a subclass raise therefore lands
as the mismatch twin (loud, never silently matched) until that rule is widened
deliberately.

Enrollment (issue #5994): community coordinates enter ONLY through an
explicitly loaded, hashed kit manifest that maps authenticated spellings to
these contracts. This module holds the provider-neutral TYPES only; no vendor
spelling may appear in code, tree-side or kit-side.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class MessagePattern:
    """A payload obligation: the observed effect's message must match this
    regex. Independently dischargeable -- undischarged (not passed, not failed)
    until the effect witness carries authenticated message content."""

    pattern: str


@dataclass(frozen=True)
class EffectMatcher:
    """A CONJUNCTION of independently dischargeable obligations (T's ruling:
    the unit of honesty is the individual obligation, never the surface
    construct). The type obligation is decidable against the observed halt;
    each payload obligation (e.g. MessagePattern from `match=`) carries its own
    closed verdict -- discharged / refuted / undischarged -- sharing the same
    observed-effect witness identity."""

    kind: str  # "raise" | "warning"
    name: str  # e.g. "ValueError", "FutureWarning"
    payload_obligations: tuple = ()  # e.g. (MessagePattern(pat),)


@dataclass(frozen=True)
class NeverSuppresses:
    pass


@dataclass(frozen=True)
class Suppresses:
    matcher: EffectMatcher


@dataclass(frozen=True)
class Expects:
    matcher: EffectMatcher


@dataclass(frozen=True)
class RuntimeSelected:
    pass


Contract = NeverSuppresses | Suppresses | Expects | RuntimeSelected


