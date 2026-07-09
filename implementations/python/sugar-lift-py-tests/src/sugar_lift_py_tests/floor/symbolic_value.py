from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.factory.factory_gap_info import GapKind, GapLocus
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
            from sugar_lift_py_tests.outcome import Complete

            spec = operation.arguments[0]
            if isinstance(spec, StringValue):
                # Non-concrete marker; FormatBuiltinSugar's wrap attaches
                # `call:format(<x>, <spec>)` with computed=None.
                return Complete(self)
        if operation.name == "__len__" and not operation.arguments:
            from sugar_lift_py_tests.outcome import Complete

            # Non-concrete marker; BuiltinCallSugar wrap attaches call:len(<x>).
            return Complete(self)
        if operation.name == "__int__" and not operation.arguments:
            from sugar_lift_py_tests.ir import _Ctor
            from sugar_lift_py_tests.outcome import Complete

            # int(format(x, "")) → x (empty-spec format is the identity stringifier
            # for the int path). call:format coordinates keep the same rule.
            if isinstance(self.term, _Ctor) and self.term.name in {
                "py.format",
                "call:format",
            }:
                if len(self.term.args) >= 2:
                    from sugar_lift_py_tests.ir import _ConstStr

                    spec = self.term.args[1]
                    if isinstance(spec, _ConstStr) and spec.value == "":
                        return Complete(SymbolicValue(self.term.args[0]))
            # Non-concrete marker; BuiltinCallSugar wrap attaches call:int(<x>).
            return Complete(self)
        if operation.name == "__hash__" and not operation.arguments:
            from sugar_lift_py_tests.outcome import Complete

            # hash never folds statically — marker only; wrap → call:hash, no companion.
            return Complete(self)
        if operation.name in {"__repr__", "__bytes__", "__abs__", "__float__", "__complex__", "__index__", "__round__", "__floor__", "__ceil__", "__trunc__"} and not operation.arguments:
            from sugar_lift_py_tests.outcome import Complete

            # Pure-value builtins on an opaque receiver: non-concrete marker for wrap.
            return Complete(self)
        # Vendor / opaque method call on a symbolic coordinate receiver
        # (`call:numpy.array(...).sum()` → `call:sum(call:numpy.array(...))`).
        # Same opaque-coordinate family as attributes (#3905) and builtins
        # (#3908): never invent a return value (computed=None).
        if not operation.name.startswith("__") and all(
            isinstance(arg, FloorValue) for arg in operation.arguments
        ):
            from sugar_lift_py_tests.floor.opaque_op_callsite import OpaqueOpCallsite
            from sugar_lift_py_tests.outcome import Complete

            return Complete(
                OpaqueOpCallsite(
                    callee=operation.name,
                    arg=self,
                    computed=None,
                    extra_args=tuple(operation.arguments),
                )
            )
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
                gap_kind=GapKind.FLOOR,
                gap_locus=GapLocus.CONSTRUCTION,
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

    def map_with(self, operation, ctx):
        del ctx
        from sugar_lift_py_tests.effect import RuntimeEffect
        from sugar_lift_py_tests.outcome import Incomplete

        return Incomplete(
            RuntimeEffect(
                "map receiver runtime boundary: SymbolicValue.map depends on "
                "the receiver's runtime collection semantics and pandas mapping "
                "rules; keep as typed red until a narrower symbolic map floor "
                f"owns this shape. blame={operation.blame}"
            )
        )

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
