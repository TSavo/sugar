from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.effect.authenticated_raise_locus import (
    AuthenticatedRaiseLocus,
    UndeterminedRaiseLocus,
)
from sugar_lift_py_tests.ir import Term


@dataclass(frozen=True)
class RaiseEffect:
    """Authenticated exceptional exit — locus identity is construction-required.

    ``occurrence`` is :class:`AuthenticatedRaiseLocus`, not ``str | None``.
    A face used as an authenticated raise is unconstructible without a named
    locus. If the locus cannot be determined, do **not** pass None and do
    **not** invent a spelling: throw, or carry undetermined locus only on
    faces that are not this type (see UndeterminedRaiseLocus; type-undetermined
    faces are mr_brown's UndeterminedRaiseEffect when that climb lands).

    BOUNDARY: this field owns LOCUS identity only. ``exception_type_coordinate``
    remains optional here until mr_brown's type-coordinate climb seals it;
    that climb owns TYPE identity. Two nouns, two doors, no dual production.

    LAW OF ONE / constructor climb: wrongness has no constructor here.
    """

    # Required first: no default. Callers that cannot supply a locus must throw
    # or stop claiming an authenticated RaiseEffect.
    occurrence: AuthenticatedRaiseLocus
    exception_name: str | None = None
    blame: str | None = None
    source_sha256: str | None = None
    exception_type_coordinate: Term | None = None
    exception_type_mro: tuple[Term, ...] | None = None
    # The value built from ``raise <exc>``.  A Name is a coordinate pointing
    # at the existing binding; a constructor call is its ordinary callsite.
    # Some runtime-generated RaiseEffects have no source exception child.
    raised_value: object | None = None
    # The constructed expression after an explicit ``from``. Host ``None``
    # means the clause was absent; explicit Python ``None`` is a NoneValue.
    cause_value: object | None = None
    # The handled occurrence active when this raise happened. This is Python's
    # ``__context__`` testimony and is distinct from an explicit ``from`` cause.
    context_effect: "RaiseEffect | None" = None
    # The expression node that published this halted edge to its parent. This
    # is distinct from ``blame``: a callee's Raise statement supplies the
    # source locus, while the enclosing Call owns the failure observed by a
    # parent expression such as ``make_receiver()[0]``.
    producer_node_owner: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.occurrence, UndeterminedRaiseLocus):
            raise TypeError(
                "RaiseEffect refuses UndeterminedRaiseLocus as occurrence. "
                "Authenticated exits require AuthenticatedRaiseLocus; "
                "undecided locus cannot impersonate an authenticated face."
            )
        if not isinstance(self.occurrence, AuthenticatedRaiseLocus):
            # Coerce only through the one door — never accept bare None.
            object.__setattr__(
                self, "occurrence", AuthenticatedRaiseLocus.of(self.occurrence)
            )

    @property
    def occurrence_id(self) -> str:
        """Stable raise-effect occurrence coordinate — always present."""
        return self.occurrence.value

    @property
    def reason(self) -> str:
        name = self.exception_name or (
            repr(self.exception_type_coordinate)
            if self.exception_type_coordinate is not None
            else "unknown exception"
        )
        locus = f" at {self.occurrence.value}"
        return (
            f"raise {name}{locus}: a Python raise effect that exits the current "
            "block and may be routed by a matching TrySugar handler"
        )
