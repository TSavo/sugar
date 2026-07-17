from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypedDict, cast

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
        return cast(Term, to_term(owner=operation))
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


_RUNTIME_OPERAND_SEAL = object()


@dataclass(frozen=True, init=False)
class RuntimeOperand:
    """A term whose value or behavior is unavailable until Python executes.

    Callers cannot turn a ground value or a description of missing machinery
    into this capability.  The only public construction door is
    :func:`genuine_runtime_operand`, which rejects decidable constants.
    """

    term: Term

    def __init__(self, term: Term, *, _seal: object) -> None:
        if _seal is not _RUNTIME_OPERAND_SEAL:
            raise TypeError(
                "RuntimeOperand is construction-closed; use "
                "genuine_runtime_operand at the audited evidence door."
            )
        if _is_lift_time_decidable(term):
            raise TypeError(
                "RuntimeOperand cannot contain a lift-time-decidable term; "
                "ground values and construction-gap prose are unconstructable."
            )
        object.__setattr__(self, "term", term)


def genuine_runtime_operand(operation: str, operand) -> RuntimeOperand:
    """Mint construction authority only for an opaque/runtime-derived term."""
    term = operand_term(operation, operand)
    if _is_lift_time_decidable(term):
        raise TypeError(
            "RuntimeEffect requires a genuine runtime-dependent operand; "
            f"{term!r} is ground/decidable at lift time. Construction-gap prose "
            "and ground values cannot mint RuntimeEffect authority. "
            "replacement=construct the exact result or FactoryPanic loudly."
        )
    return RuntimeOperand(term, _seal=_RUNTIME_OPERAND_SEAL)


def _is_lift_time_decidable(term: Term) -> bool:
    from sugar_lift_py_tests.ir import (
        _ConstBool,
        _ConstInt,
        _ConstReal,
        _ConstStr,
        _Ctor,
        _Var,
    )

    if isinstance(term, (_ConstBool, _ConstInt, _ConstReal, _ConstStr)):
        return True
    if isinstance(term, _Var):
        return False
    if isinstance(term, _Ctor):
        # A call coordinate denotes a result that does not exist until the
        # call executes, even when every argument to that call is ground.
        if term.name.startswith("call:"):
            return False
        return all(_is_lift_time_decidable(arg) for arg in term.args)
    raise TypeError(f"unknown RuntimeEffect operand term: {term!r}")


@dataclass(frozen=True)
class RuntimeEffectWitness:
    """Evidence that perfect lift-time machinery still meets a runtime operand.

    Constructed FROM the SourceFragment that owns the runtime boundary: the
    site IS the address, so an absolute or empty locus is unrepresentable by
    construction (SourceFragment.from_node normalizes filenames at the door).
    Fabricated string sites and non-term operands are refused at the door.
    """

    operation: Term
    runtime_operand: RuntimeOperand
    site: "SourceFragment"

    def __post_init__(self) -> None:
        from sugar_lift_py_tests.factory.source_fragment import SourceFragment
        from sugar_lift_py_tests.ir import Term as TermType

        if not isinstance(self.operation, TermType):
            raise TypeError(
                "RuntimeEffectWitness.operation must be a Term; got "
                f"{type(self.operation).__name__}"
            )
        if not isinstance(self.runtime_operand, RuntimeOperand):
            raise TypeError(
                "RuntimeEffectWitness.runtime_operand must be a RuntimeOperand; got "
                f"{type(self.runtime_operand).__name__}"
            )
        if not isinstance(self.runtime_operand.term, TermType):
            raise TypeError(
                "RuntimeEffectWitness.runtime_operand.term must be a Term; got "
                f"{type(self.runtime_operand.term).__name__}"
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

    @property
    def operand(self) -> Term:
        """The proof/render coordinate, projected from typed authority."""
        return self.runtime_operand.term


def runtime_effect_witness(
    operation: str,
    operand: RuntimeOperand,
    site,
) -> RuntimeEffectWitness:
    """Build the required witness from the operation's real runtime operand."""
    from sugar_lift_py_tests.ir import ctor

    if not isinstance(operand, RuntimeOperand):
        raise TypeError(
            "RuntimeEffectWitness requires a genuine runtime-dependent operand "
            "capability. Call genuine_runtime_operand(operation, operand) only "
            "for an opaque/runtime-derived value; ground values and gap prose "
            "must construct or FactoryPanic."
        )
    fragment = resolve_runtime_effect_site(site)
    return RuntimeEffectWitness(
        operation=ctor(operation, [operand.term]),
        runtime_operand=operand,
        site=fragment,
    )


class RuntimeEffectEvidence(TypedDict):
    runtime_operand: RuntimeOperand
    witness: RuntimeEffectWitness


def _runtime_operand_or_panic(operation: str, operand, site) -> RuntimeOperand:
    try:
        return genuine_runtime_operand(operation, operand)
    except TypeError as exc:
        from sugar_lift_py_tests.factory import factory_panic_gap
        from sugar_lift_py_tests.factory.factory_gap_info import GapKind, GapLocus

        factory_panic_gap(
            owner="RuntimeEffect",
            blame=resolve_runtime_effect_site(site),
            observed=f"{operation} operand={operand!r}",
            requested="genuine runtime-dependent operand",
            fix=(
                f"{exc} A decidable operand or construction-gap description "
                "must construct the exact result or panic; it cannot mint a "
                "RuntimeEffect."
            ),
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )
        raise AssertionError("factory_panic_gap returned")


def runtime_effect_evidence_from_terms(
    operation: Term,
    operand,
    site,
) -> RuntimeEffectEvidence:
    """Build evidence when the caller already owns the exact operation term."""
    runtime_operand = _runtime_operand_or_panic("RuntimeEffect", operand, site)
    witness = RuntimeEffectWitness(
        operation=operation,
        runtime_operand=runtime_operand,
        site=resolve_runtime_effect_site(site),
    )
    return {"runtime_operand": runtime_operand, "witness": witness}


def runtime_effect_evidence(
    operation: str,
    operand,
    site,
) -> RuntimeEffectEvidence:
    """Build the only lawful constructor bundle for a RuntimeEffect."""
    runtime_operand = _runtime_operand_or_panic(operation, operand, site)
    return {
        "runtime_operand": runtime_operand,
        "witness": runtime_effect_witness(operation, runtime_operand, site),
    }


@dataclass(frozen=True)
class RuntimeEffect(ABC):
    """A runtime effect: a value that does not exist until the program runs. Abstract
    by class machinery (ABC), so a generic RuntimeEffect is unrepresentable: only a
    named subclass (OSExitRuntimeEffect, ...) that declares its kind can be built.
    The KIND of runtime effect is a TYPE, not a reason string.
    """

    reason: str
    runtime_operand: RuntimeOperand
    witness: RuntimeEffectWitness

    def __post_init__(self) -> None:
        if not isinstance(self.runtime_operand, RuntimeOperand):
            raise TypeError(
                "RuntimeEffect.runtime_operand must be a RuntimeOperand; "
                "ground values and construction-gap prose are unconstructable."
            )
        if self.witness.runtime_operand != self.runtime_operand:
            raise TypeError(
                "RuntimeEffect runtime_operand must be the operand bound by its "
                "witness handle; unrelated receipt-shaped evidence is forbidden."
            )

    @abstractmethod
    def kind(self) -> type["RuntimeEffect"]:
        """The kind of this effect: its own named type. Declaring this is what makes
        a subclass a named runtime effect; the base leaves it abstract so direct
        instantiation fails at class machinery level."""
