from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

from sugar_lift_py_tests.ir import Term

if TYPE_CHECKING:
    from sugar_lift_py_tests.factory.source_fragment import SourceFragment


def resolve_runtime_effect_site(site) -> "SourceFragment":
    """Admit only a genuine SourceFragment as the witness address.

    The fragment may arrive directly, or as the ``site`` / ``blame`` field of an
    operation object that still carries the fragment (not a locus string). A
    stringly locus cannot mint evidence — reconstruct from the owning fragment
    instead of projecting blame prose into a fake address.
    """
    from sugar_lift_py_tests.factory.source_fragment import SourceFragment

    if isinstance(site, SourceFragment):
        return site
    nested = getattr(site, "site", None)
    if isinstance(nested, SourceFragment):
        return nested
    blame = getattr(site, "blame", None)
    if isinstance(blame, SourceFragment):
        return blame
    raise TypeError(
        "RuntimeEffectWitness.site must be a SourceFragment (genuine runtime "
        f"locus). Got {type(site).__name__}={site!r}. Thread the fragment that "
        "owns the boundary; do not reconstruct evidence from blame prose or "
        "string loci. replacement=pass the SourceFragment (or an operation "
        "whose .site/.blame still holds that fragment)."
    )


def operand_term(operation: str, operand) -> Term:
    """Reduce a runtime-dependent operand to a term coordinate.

    Lawful arms: an existing Term, a floor value with ``to_term``, or a ground
    Python primitive (int/float/bool/str) that IS the operand. Arbitrary objects
    may not be stringified into fabricated evidence.
    """
    from sugar_lift_py_tests.ir import (
        Term as TermType,
        bool_const,
        num,
        str_const,
    )

    if isinstance(operand, TermType):
        return operand
    to_term = getattr(operand, "to_term", None)
    if callable(to_term):
        return to_term(owner=operation)
    if type(operand) is bool:
        return bool_const(operand)
    if type(operand) is int:
        return num(operand)
    if type(operand) is str:
        return str_const(operand)
    raise TypeError(
        "RuntimeEffectWitness.operand must be a Term, a floor value with "
        f"to_term, or a ground primitive (int/bool/str); got "
        f"{type(operand).__name__}. Stringly str(object) fabricates evidence "
        "— cite the real operand term."
    )


@dataclass(frozen=True)
class RuntimeEffectWitness:
    """Evidence that perfect lift-time machinery still meets a runtime operand.

    Constructed FROM the SourceFragment that owns the runtime boundary: the
    site IS the address, so an absolute or empty locus is unrepresentable by
    construction (SourceFragment.from_node normalizes filenames at the door).
    Fabricated string sites and non-term operands are refused at the door.
    """

    operation: Term
    operand: Term
    site: "SourceFragment"

    def __post_init__(self) -> None:
        from sugar_lift_py_tests.factory.source_fragment import SourceFragment
        from sugar_lift_py_tests.ir import Term as TermType

        if not isinstance(self.operation, TermType):
            raise TypeError(
                "RuntimeEffectWitness.operation must be a Term; got "
                f"{type(self.operation).__name__}"
            )
        if not isinstance(self.operand, TermType):
            raise TypeError(
                "RuntimeEffectWitness.operand must be a Term; got "
                f"{type(self.operand).__name__}"
            )
        if not isinstance(self.site, SourceFragment):
            raise TypeError(
                "RuntimeEffectWitness.site must be a SourceFragment; got "
                f"{type(self.site).__name__}={self.site!r}. Thread the fragment "
                "that owns the boundary — string loci are unrepresentable."
            )

    @property
    def locus(self) -> str:
        """The witness address, projected for display: ``file:line:col``."""
        return str(self.site)


def runtime_effect_witness(operation: str, operand, site) -> RuntimeEffectWitness:
    """Build the required witness from the operation's real runtime operand."""
    from sugar_lift_py_tests.ir import ctor

    term = operand_term(operation, operand)
    fragment = resolve_runtime_effect_site(site)
    return RuntimeEffectWitness(
        operation=ctor(operation, [term]),
        operand=term,
        site=fragment,
    )


@dataclass(frozen=True)
class RuntimeEffect(ABC):
    """A runtime effect: a value that does not exist until the program runs. Abstract
    by class machinery (ABC), so a generic RuntimeEffect is unrepresentable: only a
    named subclass (OSExitRuntimeEffect, ...) that declares its kind can be built.
    The KIND of runtime effect is a TYPE, not a reason string.
    """

    reason: str
    witness: RuntimeEffectWitness

    @abstractmethod
    def kind(self) -> type["RuntimeEffect"]:
        """The kind of this effect: its own named type. Declaring this is what makes
        a subclass a named runtime effect; the base leaves it abstract so direct
        instantiation fails at class machinery level."""
