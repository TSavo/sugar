"""Authenticated raise locus — the missing noun behind occurrence teeth.

CLASS
    AuthenticatedRaiseLocus / UndeterminedRaiseLocus

WHY THIS OBJECT
    Presence-only teeth on ``effect.occurrence`` / ``occurrence_id`` existed
    because ``RaiseEffect.occurrence: str | None`` accepted a face with no
    locus. An auditor that only checks non-None is a confession that this
    constructor did not exist yet (T / AGENTS.md).

LAW OF ONE
    One door: :meth:`AuthenticatedRaiseLocus.of`. Empty string, None, and
    ``UndeterminedRaiseLocus`` cannot construct an authenticated locus.
    Undecided is a third value with its own type — never None on the
    authenticated type, never a fabricated placeholder string.

BOUNDARY (with mr_brown)
    This module owns LOCUS identity only. Type identity
    (``exception_type_coordinate``) is owned by the RaiseEffect type-coord
    climb (mr_brown). Neither fabricates the other.

RETIREMENT
    When every authenticated RaiseEffect carries ``AuthenticatedRaiseLocus``
    and undecided faces use ``UndeterminedRaiseLocus`` (or
    ``UndeterminedRaiseEffect`` for type-undetermined), delete presence-only
    and locus-shape teeth on occurrence / occurrence_id. The type carries
    the law.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AuthenticatedRaiseLocus:
    """Source-authenticated raise locus — unconstructible empty or undetermined.

    ``value`` is the stable occurrence string (typically file:line:col or an
    equivalent site seal). Equality is string equality of the sealed value.
    """

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str):
            raise TypeError(
                "AuthenticatedRaiseLocus refuses non-str value "
                f"({type(self.value).__name__}). Pass a locus string or use "
                "AuthenticatedRaiseLocus.of(site)."
            )
        if not self.value.strip():
            raise TypeError(
                "AuthenticatedRaiseLocus refuses empty locus. If the locus is "
                "unknown, construct UndeterminedRaiseLocus or throw — never "
                "pass None or '' through this door."
            )

    @classmethod
    def of(cls, source: object) -> "AuthenticatedRaiseLocus":
        """ONE door for authenticated loci.

        Accepts an existing locus, a non-empty str, or any object whose
        ``str(...)`` is a non-empty locus (e.g. SourceFragment). Refuses None,
        empty strings, and UndeterminedRaiseLocus (cannot impersonate).
        """
        if isinstance(source, AuthenticatedRaiseLocus):
            return source
        if isinstance(source, UndeterminedRaiseLocus):
            raise TypeError(
                "AuthenticatedRaiseLocus.of refuses UndeterminedRaiseLocus. "
                "Undecided locus is a third value — carry UndeterminedRaiseLocus "
                "explicitly, or throw if the producer is unfinished."
            )
        if source is None:
            raise TypeError(
                "AuthenticatedRaiseLocus.of refuses None. Throw (honorable "
                "unfinished producer) or construct UndeterminedRaiseLocus — "
                "never pass None."
            )
        text = str(source).strip()
        if not text:
            raise TypeError(
                "AuthenticatedRaiseLocus.of refuses empty locus text from "
                f"{type(source).__name__}. Thread a real site/fragment or "
                "construct UndeterminedRaiseLocus."
            )
        return cls(text)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True)
class UndeterminedRaiseLocus:
    """Third value: locus could not be determined.

    Structurally distinct from :class:`AuthenticatedRaiseLocus` so a nameless
    halt cannot wear authenticated clothes. Suppress/render/matchers that
    require an authenticated locus refuse this type.
    """

    reason: str = "raise locus undetermined"

    def __post_init__(self) -> None:
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise TypeError(
                "UndeterminedRaiseLocus.reason must be a non-empty str naming "
                "why the locus is undetermined"
            )

    @property
    def value(self) -> None:
        """Always None — undetermined has no authenticated occurrence string."""
        return None

    def __str__(self) -> str:
        return f"<undetermined-raise-locus: {self.reason}>"
