from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.ir import Term

from .floor_value import FloorValue


@dataclass(frozen=True)
class SymbolicValue(FloorValue):
    """A sort-neutral symbolic ProofIR term: a free variable, or a term composed
    from operations over one.

    Unlike `TermValue` (a concrete int the lift computed) or `Bv32Value` (a term
    the lift has committed to the bitvector carrier), a `SymbolicValue` carries a
    bare term and commits to NO sort. The lift stays sort-silent -- the SMT
    compiler derives the canonical carrier (Int / Real / BitVec / String) from the
    operations the term appears in. This is the carrier for a function parameter
    in a lifted body: a variable whose sort is the compiler's to decide.
    """

    term: Term
