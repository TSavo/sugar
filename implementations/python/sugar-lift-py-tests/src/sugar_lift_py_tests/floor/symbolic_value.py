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

    def project_callsite_with(self, operation, ctx):
        return operation.project_symbolic(self, ctx)

    def call_method_with(self, operation, ctx):
        del ctx
        if operation.name == "__format__" and len(operation.arguments) == 1:
            from sugar_lift_py_tests.floor.string_value import StringValue
            from sugar_lift_py_tests.ir import ctor, str_const
            from sugar_lift_py_tests.outcome import Complete

            spec = operation.arguments[0]
            if isinstance(spec, StringValue):
                return Complete(
                    SymbolicValue(ctor("py.format", [self.term, str_const(spec.value)]))
                )
        if operation.name == "__len__" and not operation.arguments:
            from sugar_lift_py_tests.ir import ctor
            from sugar_lift_py_tests.outcome import Complete

            return Complete(SymbolicValue(ctor("py.len", [self.term])))
        if operation.name == "__int__" and not operation.arguments:
            from sugar_lift_py_tests.ir import _ConstStr, _Ctor, ctor
            from sugar_lift_py_tests.outcome import Complete

            if isinstance(self.term, _Ctor) and self.term.name == "py.format":
                if (
                    len(self.term.args) == 2
                    and isinstance(self.term.args[1], _ConstStr)
                    and self.term.args[1].value == ""
                ):
                    return Complete(SymbolicValue(self.term.args[0]))
                return Complete(SymbolicValue(ctor("py.int", [self.term])))
        from sugar_lift_py_tests.effect import FactoryGapEffect
        from sugar_lift_py_tests.outcome import Incomplete

        return Incomplete(
            FactoryGapEffect(
                owner=operation.owner,
                blame=operation.blame,
                observed=f"SymbolicValue.{operation.name}",
                requested="symbolic receiver method floor",
                fix=(
                    f"add cited warrant for SymbolicValue.{operation.name} "
                    "or keep the opaque runtime method as a typed effect"
                ),
                gap_kind="Floor",
                gap_locus="Construction",
            )
        )

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

    def format_value_with(self, operation, ctx):
        return operation.format_symbolic(self, ctx)

    def bitwise_with(self, operation, ctx):
        return operation.bitwise_symbolic(self, ctx)

    def contains_with(self, operation, ctx):
        return operation.contains_symbolic(self, ctx)

    def attribute_assign_with(self, operation, ctx):
        del ctx
        from sugar_lift_py_tests.effect import RuntimeEffect
        from sugar_lift_py_tests.outcome import Incomplete

        return Incomplete(
            RuntimeEffect(
                "attribute assignment runtime boundary: symbolic receiver "
                f"`{self.term}` cannot be mutated as source object state. "
                "Python attribute assignment can invoke descriptors and "
                "__setattr__ at runtime; keep as typed red until a narrower "
                "attribute mutation floor owns this shape. "
                f"blame={operation.blame}"
            )
        )

    def setitem_with(self, operation, ctx):
        del ctx
        from sugar_lift_py_tests.effect import RuntimeEffect
        from sugar_lift_py_tests.outcome import Incomplete

        return Incomplete(
            RuntimeEffect(
                "subscript assignment runtime boundary: symbolic receiver "
                f"`{self.term}` cannot be mutated as source object state. "
                "Python subscript assignment can invoke __setitem__ and mutate "
                "runtime state; keep as typed red until a narrower mutation "
                f"floor owns this shape. blame={operation.blame}"
            )
        )
