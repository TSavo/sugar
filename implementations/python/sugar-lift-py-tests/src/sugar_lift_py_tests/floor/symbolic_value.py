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

    def test_python_type(self, value, site):
        """Dispatch a vendor type test from an existing ``python:type`` term."""
        from sugar_lift_py_tests.factory import factory_panic_gap
        from sugar_lift_py_tests.ir import _ConstStr, _Ctor

        term = self.term
        if (
            type(term) is _Ctor
            and term.name == "python:type"
            and len(term.args) == 1
            and type(term.args[0]) is _ConstStr
        ):
            return value.python_isinstance(term.args[0].value, term, site)
        factory_panic_gap(
            owner="SymbolicValue.test_python_type",
            blame=str(site),
            observed=repr(term),
            requested="identified python:type coordinate",
            fix=(
                "resolve the type name through BuiltinTypeNameSugar; unknown "
                "local classes and tuple-of-types remain loud"
            ),
        )

    def to_term(self, *, owner: str):
        del owner
        return self.term

    def truth(self, site):
        # A symbolic value EMITS the Python truth relation; the sort adjudicates later.
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.ir import py_truthy
        from sugar_lift_py_tests.outcome import Complete

        return Complete(PredicateValue(py_truthy(self.term), site))

    def length(self, site):
        # A symbolic length stays the call:len coordinate -- the vendor's stated address.
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.outcome import Complete

        return Complete(
            CallSiteValue(
                target_name="len",
                arg_values=(self,),
                parameters=(),
                term=ctor("call:len", [self.to_term(owner=str(site))]),
                body=None,
                site=site,
            )
        )

    def unary_minus(self, site):
        # Symbolic arithmetic negation: emit py.neg(term) (LAW in symbolic_term).
        del site
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.outcome import Complete

        return Complete(SymbolicValue(ctor("py.neg", [self.term])))

    def absolute(self, site):
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.outcome import Complete

        return Complete(
            CallSiteValue(
                target_name="abs",
                arg_values=(self,),
                parameters=(),
                term=ctor("call:abs", [self.to_term(owner=str(site))]),
                body=None,
                site=site,
            )
        )

    def multiply(self, other, site):
        # Symbolic multiplication: emit ``*(self, other)`` -- same BinOp Mult
        # spelling as symbolic_term (operator map Mult -> "*"). Needed so list
        # comprehension elts like ``x * 2`` reduce under a bound element
        # coordinate instead of panicking on the multiplication floor.
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.outcome import Complete

        return Complete(
            SymbolicValue(
                ctor(
                    "*",
                    [
                        self.to_term(owner=str(site)),
                        other.to_term(owner=str(site)),
                    ],
                )
            )
        )

    def power(self, other, site):
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.outcome import Complete

        return Complete(
            SymbolicValue(
                ctor(
                    "**",
                    [
                        self.to_term(owner=str(site)),
                        other.to_term(owner=str(site)),
                    ],
                )
            )
        )

    def add(self, other, site):
        # Symbolic / EUF addition: emit ``+(self, other)``. CallSiteValue dig
        # redispatches here when body is opaque; never invent a concrete sum.
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.outcome import Complete

        return Complete(
            SymbolicValue(
                ctor(
                    "+",
                    [
                        self.to_term(owner=str(site)),
                        other.to_term(owner=str(site)),
                    ],
                )
            )
        )

    def subtract(self, other, site):
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.outcome import Complete

        return Complete(
            SymbolicValue(
                ctor(
                    "-",
                    [
                        self.to_term(owner=str(site)),
                        other.to_term(owner=str(site)),
                    ],
                )
            )
        )

    def floor_divide(self, other, site):
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.outcome import Complete

        return Complete(
            SymbolicValue(
                ctor(
                    "//",
                    [
                        self.to_term(owner=str(site)),
                        other.to_term(owner=str(site)),
                    ],
                )
            )
        )

    def modulo(self, other, site):
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.outcome import Complete

        return Complete(
            SymbolicValue(
                ctor(
                    "%",
                    [
                        self.to_term(owner=str(site)),
                        other.to_term(owner=str(site)),
                    ],
                )
            )
        )

    def right_shift(self, other, site):
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.outcome import Complete

        return Complete(
            SymbolicValue(
                ctor(
                    ">>",
                    [
                        self.to_term(owner=str(site)),
                        other.to_term(owner=str(site)),
                    ],
                )
            )
        )

    def unary_plus(self, site):
        # Unary plus on a symbolic is identity (symbolic_term UAdd returns the
        # operand). Match the LAW; do not invent a py.pos spelling.
        del site
        from sugar_lift_py_tests.outcome import Complete

        return Complete(self)

    def bitwise_invert(self, site):
        # Symbolic bitwise NOT: emit py.invert(term).
        del site
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.outcome import Complete

        return Complete(SymbolicValue(ctor("py.invert", [self.term])))


    def subscript(self, index, site):
        # A symbolic receiver stays the py.subscript coordinate regardless of index.
        return self.py_subscript_coordinate(index, site)


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
        # (#3908): never invent a return value unless the payload folds.
        if not operation.name.startswith("__") and all(
            isinstance(arg, FloorValue) for arg in operation.arguments
        ):
            from sugar_lift_py_tests.floor.opaque_op_callsite import OpaqueOpCallsite
            from sugar_lift_py_tests.floor.string_value import StringValue
            from sugar_lift_py_tests.ir import _ConstStr, _Ctor
            from sugar_lift_py_tests.outcome import Complete

            computed: FloorValue | None = None
            # Foldable: b\"hi\".decode() — python:bytes hex payload is concrete.
            if (
                operation.name == "decode"
                and not operation.arguments
                and isinstance(self.term, _Ctor)
                and self.term.name == "python:bytes"
                and len(self.term.args) == 1
                and isinstance(self.term.args[0], _ConstStr)
            ):
                try:
                    text = bytes.fromhex(self.term.args[0].value).decode("utf-8")
                    computed = StringValue(text)
                except (ValueError, UnicodeDecodeError):
                    computed = None
            return Complete(
                OpaqueOpCallsite(
                    callee=operation.name,
                    arg=self,
                    computed=computed,
                    extra_args=tuple(operation.arguments),
                )
            )
        from sugar_lift_py_tests.factory.factory_gap import factory_panic_gap
        from sugar_lift_py_tests.outcome import Incomplete

        factory_panic_gap(owner=operation.owner,
                blame=operation.blame,
                observed=f"SymbolicValue.{operation.name}",
                requested="symbolic receiver method floor",
                fix=(
                    f"add cited warrant for SymbolicValue.{operation.name} "
                    "or keep the opaque runtime method as a typed effect"
                ),
                gap_kind=GapKind.FLOOR,
                gap_locus=GapLocus.CONSTRUCTION,)

    def add_with(self, operation, ctx):
        """``.add(operand)`` on a symbolic receiver.

        Numeric operands (TermValue / SymbolicValue / OpaqueOp coordinate)
        route through ``BinaryOperatorOperation(+)`` so free ``z.add(1)`` is
        the joinable term ``+(z, 1)`` — same arithmetic as ``z + 1``, and the
        AddSugar witness seed stays proof-bearing.

        Vendor/opaque operands (arrays, undiggable callsites) mint
        ``call:add(self, operand)`` with ``computed=None`` — never invent a
        placement/array sum (pandas BlockPlacement residual).
        """
        from sugar_lift_py_tests.floor.opaque_op_callsite import OpaqueOpCallsite
        from sugar_lift_py_tests.floor.term_value import TermValue
        from sugar_lift_py_tests.operations.binary_operator_operation import (
            BinaryOperatorOperation,
        )
        from sugar_lift_py_tests.operations.perform_operation import perform_operation
        from sugar_lift_py_tests.outcome import Complete

        operand = operation.operand
        if isinstance(operand, (TermValue, SymbolicValue, OpaqueOpCallsite)):
            return perform_operation(
                owner=operation.owner,
                blame=operation.blame,
                receiver=self,
                operation=BinaryOperatorOperation(
                    operator="+",
                    right=operand,
                    owner=operation.owner,
                    blame=operation.blame,
                ),
                ctx=ctx,
            )
        return Complete(
            OpaqueOpCallsite(
                callee="add",
                arg=self,
                computed=None,
                extra_args=(operand,),
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

    def async_iter_with(self, operation, ctx):
        """async for over a free/symbolic iterable — typed red, not floor panic."""
        del ctx
        from sugar_lift_py_tests.effect import RuntimeEffect
        from sugar_lift_py_tests.outcome import Incomplete

        return Incomplete(
            RuntimeEffect(
                "async for runtime boundary: symbolic iterable cannot be "
                "async-iterated without a concrete async-iterator floor; "
                f"owner={operation.owner}; keep as typed red until a narrower "
                f"async-iter floor owns this shape. blame={operation.blame}"
            )
        )

    def await_with(self, operation, ctx):
        """await on a free/symbolic awaitable — typed red, not floor panic."""
        del ctx
        from sugar_lift_py_tests.effect import RuntimeEffect
        from sugar_lift_py_tests.outcome import Incomplete

        return Incomplete(
            RuntimeEffect(
                "await runtime boundary: symbolic awaitable cannot be forced "
                "without a concrete awaitable floor; "
                f"owner={operation.owner}; keep as typed red until a narrower "
                f"await floor owns this shape. blame={operation.blame}"
            )
        )

    def async_context_manager_with(self, operation, ctx):
        """async with over a free/symbolic manager — typed red, not floor panic."""
        del ctx
        from sugar_lift_py_tests.effect import RuntimeEffect
        from sugar_lift_py_tests.outcome import Incomplete

        return Incomplete(
            RuntimeEffect(
                "async with runtime boundary: symbolic manager cannot enter "
                "an async context without a concrete async-CM floor; "
                f"owner={operation.owner}; keep as typed red until a narrower "
                f"async-with floor owns this shape. blame={operation.blame}"
            )
        )

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

    def setitem(self, index, value, site):
        del index, value
        from sugar_lift_py_tests.effect import SubscriptStoreRuntimeEffect
        from sugar_lift_py_tests.outcome import Incomplete

        return Incomplete(
            SubscriptStoreRuntimeEffect(
                "subscript assignment runtime boundary: symbolic receiver "
                f"`{self.term}` may invoke __setitem__; site={site}"
            )
        )
