from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .floor_value import FloorValue


@dataclass(frozen=True)
class RealValue(FloorValue):
    """A concrete Real-sorted value -- the Real refinement of the numeric hierarchy,
    distinct from the Int-sorted TermValue.

    The value is a CANONICAL DECIMAL STRING, never a Python float -- the same discipline
    as the IR's `_ConstReal` / `real_lit`: a float has no deterministic textual form and
    the term is hashed into the contract CID, so it must ride as exact, content-
    addressable decimal text. It lowers to `real_lit(decimal)` of `Real()` sort; the
    smt-lib compiler then declares any operand meeting it as `Real`, never `Int` (sort
    inference flows from the literal outward), and a float squatting in `Int` is exactly
    the sort error the verify dialect refuses rather than risk a false discharge.

    Rung 1 of the refinement: the typed distinction, so `3.0 != 3`. The next rungs are
    real ARITHMETIC (e.g. division: `1/3` has no finite decimal) and TOLERANCE (`0.1 +
    0.2 != 0.3` exactly, but Real-with-tolerance must agree) -- the existing decimal-
    tolerance lift and its `|a-b| < T` lowering are the model to mirror, not float math.
    """

    decimal: str

    @classmethod
    def from_python(cls, value: float) -> "RealValue":
        # Canonicalize through Decimal(repr(...)) so the text is exact and deterministic
        # -- never str(float) arithmetic. (Source-text-exact decimals are a finer rung.)
        return cls(str(Decimal(repr(value))))
