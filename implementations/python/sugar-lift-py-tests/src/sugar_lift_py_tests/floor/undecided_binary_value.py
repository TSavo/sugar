from __future__ import annotations

from dataclasses import dataclass, field

from .floor_value import ExceptionalDispositionV1, FloorValue
from .symbolic_value import SymbolicValue


@dataclass(frozen=True, kw_only=True)
class UndecidedBinaryOperationValue(SymbolicValue):
    """A native binary dispatch with both completion and exceptional faces live.

    The completion face remains an ordinary symbolic value. The additional
    testimony is producer-owned: Python has not selected ``__op__`` or
    ``__rop__``, so an assertion boundary may not silently treat the operation
    as completed and may not invent the exception it expected.
    """

    operator: str
    left: FloorValue = field(compare=False, repr=False)
    right: FloorValue = field(compare=False, repr=False)

    def exceptional_disposition(self) -> ExceptionalDispositionV1:
        return ExceptionalDispositionV1.UNDECIDED


def undecided_binary_operation(left, right, site, operator):
    """Construct the one native undecided-dispatch completion coordinate."""
    from sugar_lift_py_tests.ir import ctor
    from sugar_lift_py_tests.outcome import Complete

    return Complete(
        UndecidedBinaryOperationValue(
            term=ctor(
                operator,
                [
                    left.to_term(owner=str(site)),
                    right.to_term(owner=str(site)),
                ],
            ),
            operator=operator,
            left=left,
            right=right,
        )
    )
