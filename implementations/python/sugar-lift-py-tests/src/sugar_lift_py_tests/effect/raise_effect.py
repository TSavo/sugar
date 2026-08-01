from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.effect.authenticated_raise_locus import (
    AuthenticatedRaiseLocus,
    UndeterminedRaiseLocus,
)
from sugar_lift_py_tests.ir import Term


@dataclass(frozen=True)
class RaiseEffect:
    """Authenticated exceptional exit — type AND locus required at construction.

    TYPE IDENTITY (mr_brown): ``exception_type_coordinate: Term`` — not Optional.
    LOCUS IDENTITY (mr_blue): ``occurrence: AuthenticatedRaiseLocus`` — not Optional.

    If type identity cannot be determined: ``UndeterminedRaiseEffect`` (brown).
    If locus cannot be determined: do not mint this type; throw or carry
    ``UndeterminedRaiseLocus`` only on non-authenticated faces.

    LAW OF ONE: wrongness has no constructor. Neither field fabricates the other.
    """

    # Both required, no defaults — unconstructible without both nouns.
    exception_type_coordinate: Term
    occurrence: AuthenticatedRaiseLocus
    exception_name: str | None = None
    blame: str | None = None
    source_sha256: str | None = None
    exception_type_mro: tuple[Term, ...] | None = None
    raised_value: object | None = None
    cause_value: object | None = None
    context_effect: "RaiseEffect | UndeterminedRaiseEffect | None" = None
    producer_node_owner: str | None = None

    def __post_init__(self) -> None:
        if self.exception_type_coordinate is None:
            raise TypeError(
                "RaiseEffect refuses exception_type_coordinate=None. "
                "Authenticated exceptional exits require a named type coordinate "
                "at construction. If identity is undetermined, construct "
                "UndeterminedRaiseEffect or throw SugarNotWritten — never pass None."
            )
        if isinstance(self.occurrence, UndeterminedRaiseLocus):
            raise TypeError(
                "RaiseEffect refuses UndeterminedRaiseLocus as occurrence. "
                "Authenticated exits require AuthenticatedRaiseLocus."
            )
        if not isinstance(self.occurrence, AuthenticatedRaiseLocus):
            object.__setattr__(
                self, "occurrence", AuthenticatedRaiseLocus.of(self.occurrence)
            )

    @classmethod
    def for_builtin(
        cls,
        exception_name: str,
        *,
        occurrence: object | None = None,
        blame: str | None = None,
        source_sha256: str | None = None,
        raised_value: object | None = None,
        cause_value: object | None = None,
        context_effect: object | None = None,
        producer_node_owner: str | None = None,
        exception_type_mro: tuple[Term, ...] | None = None,
    ) -> "RaiseEffect":
        """One door for language-owned exception classes (tests + ground producers).

        Requires an authenticated locus (``occurrence`` or ``blame`` via
        AuthenticatedRaiseLocus.of). Unknown exception names throw.
        """
        from sugar_lift_py_tests.floor.ground_exit import _builtin_exception_identity

        coordinate, mro = _builtin_exception_identity(exception_name)
        if coordinate is None:
            raise TypeError(
                f"RaiseEffect.for_builtin: {exception_name!r} has no language-owned "
                "exception_type_identity. Supply exception_type_coordinate explicitly "
                "for authenticated non-builtin types, or throw if identity is unfinished."
            )
        locus_source = occurrence if occurrence is not None else blame
        if locus_source is None:
            raise TypeError(
                "RaiseEffect.for_builtin requires an authenticated locus "
                "(occurrence= or blame=). Throw if unfinished — never omit."
            )
        return cls(
            exception_type_coordinate=coordinate,
            occurrence=AuthenticatedRaiseLocus.of(locus_source),
            exception_name=exception_name,
            blame=blame,
            source_sha256=source_sha256,
            exception_type_mro=(
                exception_type_mro if exception_type_mro is not None else mro
            ),
            raised_value=raised_value,
            cause_value=cause_value,
            context_effect=context_effect,
            producer_node_owner=producer_node_owner,
        )

    @property
    def occurrence_id(self) -> str:
        """Stable raise-effect occurrence — always present on authenticated faces."""
        return self.occurrence.value

    @property
    def reason(self) -> str:
        name = self.exception_name or repr(self.exception_type_coordinate)
        locus = f" at {self.occurrence.value}"
        return (
            f"raise {name}{locus}: a Python raise effect that exits the current "
            "block and may be routed by a matching TrySugar handler"
        )


@dataclass(frozen=True)
class UndeterminedRaiseEffect:
    """Exceptional halt without authenticated type identity (mr_brown).

    Distinct from RaiseEffect so a nameless halt cannot impersonate an
    authenticated exceptional exit. Locus may be AuthenticatedRaiseLocus,
    UndeterminedRaiseLocus, or absent — type-undetermined is the primary noun.
    """

    blame: str | None = None
    source_sha256: str | None = None
    occurrence: AuthenticatedRaiseLocus | UndeterminedRaiseLocus | str | None = None
    raised_value: object | None = None
    cause_value: object | None = None
    context_effect: "RaiseEffect | UndeterminedRaiseEffect | None" = None
    producer_node_owner: str | None = None
    exception_name: str | None = None

    @property
    def occurrence_id(self) -> str | None:
        occ = self.occurrence
        if isinstance(occ, AuthenticatedRaiseLocus):
            return occ.value
        if isinstance(occ, UndeterminedRaiseLocus):
            return None
        if isinstance(occ, str) and occ.strip():
            return occ
        return self.blame

    @property
    def exception_type_coordinate(self) -> None:
        return None

    @property
    def exception_type_mro(self) -> None:
        return None

    @property
    def reason(self) -> str:
        locus = f" at {self.blame}" if self.blame is not None else ""
        return (
            f"raise with undetermined exception identity{locus}: "
            "not an authenticated exceptional exit"
        )
