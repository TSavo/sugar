from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.ir import Term


@dataclass(frozen=True)
class RuntimeEffectWitness:
    """Evidence that perfect lift-time machinery still meets a runtime operand."""

    operation: Term
    operand: Term
    locus: str

    def __post_init__(self) -> None:
        if not self.locus:
            raise ValueError("RuntimeEffectWitness requires a stable source locus")


def runtime_effect_witness(operation: str, operand, locus) -> RuntimeEffectWitness:
    """Build the required witness from the operation's real runtime operand."""
    from sugar_lift_py_tests.ir import Term, ctor, str_const

    if isinstance(operand, Term):
        term = operand
    elif hasattr(operand, "to_term"):
        term = operand.to_term(owner=operation)
    else:
        term = str_const(str(operand))
    return RuntimeEffectWitness(
        operation=ctor(operation, [term]), operand=term, locus=str(locus)
    )


@dataclass(frozen=True)
class RuntimeEffect:
    """A runtime effect: a value that does not exist until the program runs. Abstract --
    never constructed directly. The KIND of runtime effect is a TYPE, so you build a
    named subclass (OSExitRuntimeEffect, ...); a generic RuntimeEffect does not exist."""

    reason: str
    witness: RuntimeEffectWitness | None = None

    def __post_init__(self) -> None:
        if type(self) is RuntimeEffect:
            raise TypeError(
                "RuntimeEffect is abstract and cannot be constructed directly; build a "
                "named runtime effect (e.g. OSExitRuntimeEffect). The kind of effect is "
                "a type, not a reason string."
            )
        if self.witness is None:
            raise TypeError(
                f"{type(self).__name__} requires RuntimeEffectWitness(operation, "
                "runtime-dependent operand, locus); without that witness the "
                "path must construct or FactoryPanic"
            )
