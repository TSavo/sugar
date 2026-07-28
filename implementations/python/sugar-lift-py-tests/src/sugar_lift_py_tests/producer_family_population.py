"""One typed predicate for producer-family population membership.

Membership consumes native boundary testimony and authenticated execution
ownership.  Manager names and syntactic child inventories are deliberately not
part of the input vocabulary, so neither can become a population rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ProducerFamily(str, Enum):
    SUBSCRIPT = "Subscript"
    BINOP = "BinOp"
    COMPARE = "Compare"
    ATTRIBUTE = "Attribute"
    UNARYOP = "UnaryOp"
    BOOLOP = "BoolOp"


class FailingNodeFamily(str, Enum):
    SUBSCRIPT = "Subscript"
    BINOP = "BinOp"
    COMPARE = "Compare"
    ATTRIBUTE = "Attribute"
    UNARYOP = "UnaryOp"
    BOOLOP = "BoolOp"
    CALL = "Call"


class NativeBoundaryKind(str, Enum):
    EFFECT = "effect-boundary"


@dataclass(frozen=True)
class AuthenticatedCompletedOwnership:
    """A positive Completed edge reached the body root."""

    root_family: ProducerFamily


@dataclass(frozen=True)
class AuthenticatedHaltOwnership:
    """An authenticated halted edge names the node that halted first."""

    root_family: ProducerFamily
    failing_family: FailingNodeFamily


@dataclass(frozen=True)
class UndecidedOwnership:
    """No authenticated edge decides whether the body root was reached."""

    root_family: ProducerFamily


FailingNodeOwnership = (
    AuthenticatedCompletedOwnership | AuthenticatedHaltOwnership | UndecidedOwnership
)


@dataclass(frozen=True)
class ProducerFamilyPopulationWitness:
    boundary_kind: NativeBoundaryKind
    ownership: FailingNodeOwnership


class PopulationMembership(str, Enum):
    MEMBER = "member"
    REATTRIBUTED = "re-attributed"
    UNDECIDED = "undecided"


@dataclass(frozen=True)
class ProducerFamilyPopulationDecision:
    membership: PopulationMembership
    family: ProducerFamily | FailingNodeFamily | None


def producer_family_population_membership(
    witness: ProducerFamilyPopulationWitness,
) -> ProducerFamilyPopulationDecision:
    """Decide membership once from native, authenticated testimony.

    Both native effect-boundary kinds use the same producer population law. A
    completed edge is positive evidence that evaluation reached the root. A
    halted edge belongs to the node that emitted it; when that node is a child,
    the body is re-attributed before the root operation. Missing testimony is a
    third value and never becomes an empty successful execution.
    """
    if not isinstance(witness.boundary_kind, NativeBoundaryKind):
        raise TypeError("population membership requires a native boundary kind")
    ownership = witness.ownership
    if isinstance(ownership, UndecidedOwnership):
        return ProducerFamilyPopulationDecision(PopulationMembership.UNDECIDED, None)
    if isinstance(ownership, AuthenticatedCompletedOwnership):
        return ProducerFamilyPopulationDecision(
            PopulationMembership.MEMBER, ownership.root_family
        )
    if isinstance(ownership, AuthenticatedHaltOwnership):
        if ownership.failing_family.value == ownership.root_family.value:
            return ProducerFamilyPopulationDecision(
                PopulationMembership.MEMBER, ownership.root_family
            )
        return ProducerFamilyPopulationDecision(
            PopulationMembership.REATTRIBUTED, ownership.failing_family
        )
    raise TypeError("population membership requires typed failing-node ownership")
