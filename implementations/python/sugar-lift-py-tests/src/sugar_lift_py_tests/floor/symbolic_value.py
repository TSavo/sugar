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

    def to_term(self, *, owner: str):
        del owner
        return self.term

    def binary_operator_with(self, operation, ctx):
        return operation.binary_symbolic(self, ctx)

    def unary_operator_with(self, operation, ctx):
        return operation.unary_symbolic(self, ctx)

    def subscript_with(self, operation, ctx):
        return operation.subscript_symbolic(self, ctx)

    def project_sequence_with(self, operation, ctx):
        return operation.project_symbolic(self, ctx)

    def str_with(self, operation, ctx):
        return operation.str_symbolic(self, ctx)

    def bitwise_with(self, operation, ctx):
        return operation.bitwise_symbolic(self, ctx)

    def contains_with(self, operation, ctx):
        return operation.contains_symbolic(self, ctx)
