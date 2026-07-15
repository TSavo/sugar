from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sugar_lift_py_tests.ir import Term

if TYPE_CHECKING:
    from sugar_lift_py_tests.factory.source_fragment import SourceFragment


@dataclass(frozen=True)
class RuntimeEffectWitness:
    """Evidence that perfect lift-time machinery still meets a runtime operand.

    Constructed FROM the SourceFragment that owns the runtime boundary: the
    site IS the address, so an absolute or empty locus is unrepresentable by
    construction (SourceFragment.from_node normalizes filenames at the door).
    """

    operation: Term
    operand: Term
    site: "SourceFragment"

    @property
    def locus(self) -> str:
        """The witness address, projected for display: ``file:line:col``."""
        return str(self.site)


def runtime_effect_witness(operation: str, operand, site) -> RuntimeEffectWitness:
    """Build the required witness from the operation's real runtime operand."""
    from sugar_lift_py_tests.ir import Term, ctor, str_const

    if isinstance(operand, Term):
        term = operand
    elif hasattr(operand, "to_term"):
        term = operand.to_term(owner=operation)
    else:
        term = str_const(str(operand))
    return RuntimeEffectWitness(
        operation=ctor(operation, [term]), operand=term, site=site
    )


@dataclass(frozen=True)
class RuntimeEffect:
    """A runtime effect: a value that does not exist until the program runs. Abstract --
    never constructed directly. The KIND of runtime effect is a TYPE, so you build a
    named subclass (OSExitRuntimeEffect, ...); a generic RuntimeEffect does not exist.
    """

    reason: str
    witness: RuntimeEffectWitness

    def __post_init__(self) -> None:
        if type(self) is RuntimeEffect:
            raise TypeError(
                "RuntimeEffect is abstract and cannot be constructed directly; build a "
                "named runtime effect (e.g. OSExitRuntimeEffect). The kind of effect is "
                "a type, not a reason string."
            )
