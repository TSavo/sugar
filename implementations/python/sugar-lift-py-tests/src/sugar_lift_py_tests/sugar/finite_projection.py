"""The closed finite-projection decision for comprehensions (#7347).

`ComprehensionSugar._finite_map` used to answer `Outcome | None`, and the bare
`None` stood for AT LEAST FOUR DISTINCT FACTS:

1. the iterable genuinely has no finite-member roster;
2. a destructuring target's authenticated `TargetPatternV1` was not found;
3. the context carries no temporal projection capability;
4. replacing the temporal context failed.

`_after_iterable` erased all four into one symbolic fallback and `_complete`
issued `Complete(ComprehensionValue(term))` with `finite_elements=None`. A
comprehension whose finite projection was LOST TO A STRANDED LOOKUP therefore
reported the same verdict as a genuinely unbounded one, and no downstream
consumer could tell them apart.

THE LAW. Lawful inapplicability may produce `Complete`. A FAILED AUTHENTICATED
LOOKUP MAY NOT: it must refuse, naming construct, coordinate and shape.

The carrier is closed on purpose, and the closure is TYPE-LEVEL rather than
guarded. `FiniteProjectionNonSuccessV1` is an `Enum`, so a fifth cause cannot
be minted at a callsite -- it requires editing this module, which makes every
exhaustive `match` over it fail loudly until it is revisited. A guard can be
bypassed by a new callsite; a missing constructor cannot.

`Projected` transports the existing `Outcome` and is NOT a fifth non-success
cause. Absence and lookup-failure never share a representation here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class FiniteProjectionNonSuccessV1(Enum):
    """Why a finite projection was not produced. Closed; exhaustively matched."""

    LAWFULLY_INAPPLICABLE = "lawfully-inapplicable"
    """The iterable exposes no finite-member roster.

    Symbolic `Complete` is HONEST here: `ComprehensionValue.finite_elements`
    documents `None` as "no exact finite-member testimony exists".
    """

    PROJECTION_UNAVAILABLE_IN_CONTEXT = "projection-unavailable-in-context"
    """The context carries no temporal projection capability.

    A DIFFERENT lawful reason from `LAWFULLY_INAPPLICABLE`: the iterable may be
    a perfectly exact roster; this construction simply cannot be evaluated
    against the context it was handed. Kept apart so the two are never
    conflated by a later reader.
    """

    AUTHENTICATED_LOOKUP_FAILED = "authenticated-lookup-failed"
    """An ENROLLED consumer's `TargetPatternV1` was not found.

    A CONSTRUCTION REFUSAL. The producer OWED testimony for this slot
    (#7348's `TargetPatternEnrolledV1`) and the lookup came back empty --
    the relation is stranded, not absent. This must NEVER reach `Complete`.
    """

    REPLACEMENT_FAILED = "replacement-failed"
    """The temporal context could not be replaced. Its own typed terminal.

    Not a statement about the iterable and not a lawful inapplicability: the
    projection machinery itself failed, and saying "not finite" instead would
    blame the source for a defect in the evaluator.
    """


@dataclass(frozen=True)
class Projected:
    """A finite projection was produced. Transports the existing `Outcome`."""

    outcome: object

    def __post_init__(self) -> None:
        if self.outcome is None:
            raise TypeError("Projected transports an Outcome, never None")
        from sugar_lift_py_tests.outcome.outcome import Outcome

        if not isinstance(self.outcome, Outcome):
            raise TypeError(
                "Projected transports an Outcome; got "
                f"{type(self.outcome).__name__}"
            )


@dataclass(frozen=True)
class NotProjected:
    """No finite projection, WITH the producer-owned cause still attached."""

    reason: FiniteProjectionNonSuccessV1

    def __post_init__(self) -> None:
        if type(self.reason) is not FiniteProjectionNonSuccessV1:
            raise TypeError(
                "NotProjected requires an exact FiniteProjectionNonSuccessV1; "
                f"got {type(self.reason).__name__}"
            )


FiniteProjectionDecisionV1 = Projected | NotProjected


class FiniteProjectionRefusalV1(Exception):
    """A finite-projection decision that may not become a verdict.

    Named, and carrying the three things a reader needs to act: the CONSTRUCT
    (comprehension kind), the COORDINATE (the generator's binding coordinate)
    and the SHAPE (the target shape whose pattern was owed).
    """

    def __init__(
        self,
        reason: FiniteProjectionNonSuccessV1,
        *,
        construct: str,
        coordinate: str,
        shape: str,
        site: object = None,
    ) -> None:
        self.reason = require_finite_projection_non_success(
            reason, owner="FiniteProjectionRefusalV1.reason"
        )
        self.construct = construct
        self.coordinate = coordinate
        self.shape = shape
        self.site = site
        super().__init__(
            f"{reason.value}: construct={construct} coordinate={coordinate} "
            f"shape={shape} site={site!r}"
        )


def require_finite_projection_non_success(
    value: object, *, owner: str
) -> FiniteProjectionNonSuccessV1:
    if type(value) is not FiniteProjectionNonSuccessV1:
        raise TypeError(
            f"{owner} requires an exact FiniteProjectionNonSuccessV1; "
            f"got {type(value).__name__}"
        )
    return value


def require_finite_projection_decision(value: object, *, owner: str):
    """Reject `None`, foreign values, and undeclared variants at the boundary.

    This is the memo boundary #7347 asks for. It exists so that a future cause
    cannot arrive as a bare sentinel: it must be a declared variant of the
    type, which in turn forces a new match arm.
    """
    if value is None:
        raise TypeError(f"{owner} requires a FiniteProjectionDecisionV1, never None")
    if type(value) is Projected:
        return value
    if type(value) is NotProjected:
        require_finite_projection_non_success(value.reason, owner=owner)
        return value
    raise TypeError(
        f"{owner} requires Projected or NotProjected; got {type(value).__name__}"
    )


__all__ = [
    "FiniteProjectionDecisionV1",
    "FiniteProjectionNonSuccessV1",
    "FiniteProjectionRefusalV1",
    "NotProjected",
    "Projected",
    "require_finite_projection_decision",
    "require_finite_projection_non_success",
]
