from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.gap.info import GapKind, GapLocus
from sugar_lift_py_tests.ir import Term

from .floor_value import _BINARY_OPERATOR_COORDINATE, FloorValue


def _pep604_type_union_leaves(term: Term) -> tuple[Term, ...] | None:
    """Flatten a ground PEP 604 ``|`` tree of ``python:type`` leaves.

    Returns ``None`` when any arm is not a type coordinate (or nested union of
    them). Callers keep the dynamic / loud path for non-type ``|`` operands.
    """
    from sugar_lift_py_tests.ir import _ConstStr, _Ctor

    if type(term) is _Ctor and term.name == "python:type":
        if len(term.args) == 1 and type(term.args[0]) is _ConstStr:
            return (term,)
        return None
    if type(term) is _Ctor and term.name == "|" and len(term.args) == 2:
        left = _pep604_type_union_leaves(term.args[0])
        right = _pep604_type_union_leaves(term.args[1])
        if left is None or right is None:
            return None
        return (*left, *right)
    return None


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
    formal_coordinate: object | None = None

    def denotes_value(self) -> bool:
        """This floor value denotes a Python runtime value."""
        return True

    def runtime_type_is_decided(self) -> bool:
        """Undecided: this is an unresolved term: nothing names its Python type.

        Which ``__op__``/``__rop__`` Python would select for an
        operation over this value is therefore undecided too, so a binary
        operation reaches the named producer refusal rather than standing on a
        ground field law or claiming completion.
        """
        return False

    def denotes_a_value(self) -> bool:
        # A symbolic term IS a value whose identity is not decidable yet --
        # membership over it is an obligation, never a gap.
        return True

    def python_isinstance(self, type_name: str, type_term, site):
        """Fold ground ``python:*`` data ctors against a named builtin type.

        ``isinstance(b'ab', bytes)`` must reduce to the True/False floor so
        function posts and Derived EUF residue pin Bool, not an open
        ``adt.is_python_type`` atom that soft-SATs lies (#4387
        builtin_type_name_isinstance). Unknown / non-ground terms stay on the
        reserved tester atom via the FloorValue default.
        """
        from sugar_lift_py_tests.ir import _Ctor
        from sugar_lift_py_tests.outcome import Complete
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        # Closed map: ctor name → Python type name the vendor uses in isinstance.
        ground_type_names = {
            "python:bytes": "bytes",
            "python:bytearray": "bytearray",
            "python:list": "list",
            "python:dict": "dict",
            "python:set": "set",
            "python:frozenset": "frozenset",
            "python:tuple": "tuple",
            "tuple": "tuple",
            "None": "NoneType",
            "py.ellipsis": "ellipsis",
            "py.complex": "complex",
        }
        term = self.term
        if type(term) is _Ctor and term.name in ground_type_names:
            matches = ground_type_names[term.name] == type_name
            return Complete(
                TrueBoolLiteralSugar(site=site)
                if matches
                else FalseBoolLiteralSugar(site=site)
            )
        return super().python_isinstance(type_name, type_term, site)

    def test_python_type(self, value, site):
        """Dispatch a vendor type test from an existing ``python:type`` term.

        PEP 604 runtime unions of type coordinates (``str | bytes``) are the
        same multi-arm isinstance surface as tuple-of-types. They reduce to a
        ground ``|`` of ``python:type`` leaves — never mint RuntimeEffect for
        that decidable union (#5340 sklearn test_stats / _pytest.approx path).
        """
        from sugar_lift_py_tests.ir import _ConstStr, _Ctor, ctor

        term = self.term
        if (
            type(term) is _Ctor
            and term.name == "python:type"
            and len(term.args) == 1
            and type(term.args[0]) is _ConstStr
        ):
            return value.python_isinstance(term.args[0].value, term, site)

        type_terms = _pep604_type_union_leaves(term)
        if type_terms is not None:
            # Same disjunction as ``isinstance(x, (T, U, …))`` — reuse the
            # TupleValue multi-arm collector; no vendor-path special case.
            from sugar_lift_py_tests.floor.tuple_value import TupleValue

            return TupleValue(
                tuple(SymbolicValue(type_term) for type_term in type_terms)
            ).test_python_type(value, site)

        from sugar_lift_py_tests.effect import (
            DynamicTypeOperandRuntimeEffect,
            runtime_effect_evidence_from_terms,
        )
        from sugar_lift_py_tests.outcome import Incomplete
        from sugar_lift_py_tests.sugar.floor_terms import floor_to_term

        operation = ctor(
            "adt.is_python_type",
            [floor_to_term(value, owner="isinstance value"), term],
        )
        return Incomplete(
            DynamicTypeOperandRuntimeEffect(
                "dynamic isinstance type operand runtime boundary: "
                f"Python must resolve {term!r} as a type or raise TypeError; "
                f"site={site}",
                **runtime_effect_evidence_from_terms(
                    operation,
                    term,
                    site,
                ),
            )
        )

    def test_python_subtype(self, supertype, site):
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.ir import atomic
        from sugar_lift_py_tests.outcome import Complete

        return Complete(
            PredicateValue(
                atomic(
                    "python.subtype",
                    [
                        self.to_term(owner="python.issubclass subtype"),
                        supertype.to_term(owner="python.issubclass supertype"),
                    ],
                ),
                site,
                operand_callsites=(*self.callsites(), *supertype.callsites()),
            )
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

    def is_identical(self, other, site):
        from sugar_lift_py_tests.ir import _ConstStr, _Ctor

        left = self.term
        right = other.term if type(other) is SymbolicValue else None
        if (
            type(left) is _Ctor
            and left.name == "python:type"
            and len(left.args) == 1
            and type(left.args[0]) is _ConstStr
            and type(right) is _Ctor
            and right.name == "python:type"
            and len(right.args) == 1
            and type(right.args[0]) is _ConstStr
        ):
            from sugar_lift_py_tests.outcome import Complete
            from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
                FalseBoolLiteralSugar,
            )
            from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
                TrueBoolLiteralSugar,
            )

            return Complete(
                TrueBoolLiteralSugar(site=site)
                if left.args[0].value == right.args[0].value
                else FalseBoolLiteralSugar(site=site)
            )
        return super().is_identical(other, site)

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
                term=ctor(
                    "call:len",
                    [self.to_term(owner=str(site))],
                    symbol_kind="builtin",
                ),
                body=None,
                site=site,
            )
        )

    def append_with(self, value, site):
        from sugar_lift_py_tests.effect import (
            AppendRuntimeEffect,
            runtime_effect_evidence,
        )
        from sugar_lift_py_tests.outcome import Incomplete

        return Incomplete(
            AppendRuntimeEffect(
                "append runtime boundary: symbolic receiver has no constructed "
                f"list post-state; value={value.to_term(owner=str(site))!r}; "
                f"site={site}",
                **runtime_effect_evidence("py.append", self, site),
            )
        )

    def unary_minus(self, site):
        # The term does not state a runtime type, so it cannot decide whether
        # ``-`` returns a value or raises TypeError.  A symbolic ``py.neg``
        # coordinate for the success face would erase that exceptional face.
        return super().unary_minus(site)

    def absolute(self, site):
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.outcome import Complete

        return Complete(
            CallSiteValue(
                target_name="abs",
                arg_values=(self,),
                parameters=(),
                term=ctor(
                    "call:abs",
                    [self.to_term(owner=str(site))],
                    symbol_kind="builtin",
                ),
                body=None,
                site=site,
            )
        )

    def multiply(self, other, site):
        # Symbolic numeric multiplication keeps the native coordinate. A symbolic
        # value used as a sequence repetition count has not proved Python's
        # __index__ contract, so it must remain a named construction gap.
        from sugar_lift_py_tests.floor.list_value import ListValue

        if type(other) is ListValue:
            return other.multiply(self, site)

        return self._runtime_binary_dispatch(other, site, "*")

    def power(self, other, site):
        return self._runtime_binary_dispatch(other, site, "**")

    def add(self, other, site):
        return self._runtime_binary_dispatch(other, site, "+")

    def subtract(self, other, site):
        return self._runtime_binary_dispatch(other, site, "-")

    def divide(self, other, site):
        return self._arithmetic_dispatch(other, site, "/")

    def floor_divide(self, other, site):
        return self._arithmetic_dispatch(other, site, "//")

    def modulo(self, other, site):
        return self._arithmetic_dispatch(other, site, "%")

    def _arithmetic_dispatch(self, other, site, operator):
        return self._runtime_binary_dispatch(other, site, operator)

    def right_shift(self, other, site):
        return self._runtime_binary_dispatch(other, site, ">>")

    def bitwise_and(self, other, site):
        return self._runtime_bitwise_dispatch(other, site, "&")

    def bitwise_xor(self, other, site):
        return self._runtime_bitwise_dispatch(other, site, "^")

    def bitwise_or(self, other, site):
        return self._runtime_bitwise_dispatch(other, site, "|")

    def left_shift(self, other, site):
        return self._runtime_bitwise_dispatch(other, site, "<<")

    def _runtime_bitwise_dispatch(self, other, site, operator):
        return self._runtime_binary_dispatch(other, site, operator)

    def _runtime_binary_dispatch(self, other, site, operator):
        from sugar_lift_py_tests.floor.guarded_value import GuardedValue

        owner = next(
            method
            for method, coordinate in _BINARY_OPERATOR_COORDINATE.items()
            if coordinate == operator
        )
        if isinstance(other, GuardedValue):
            return other.map_from_left(owner, self, site)
        denotes_other = getattr(other, "denotes_value", None)
        if callable(denotes_other) and denotes_other():
            from sugar_lift_py_tests.effect import RaiseEffect
            from sugar_lift_py_tests.ir import atomic, ctor, str_const
            from sugar_lift_py_tests.outcome import ExitSet
            from sugar_lift_py_tests.outcome.exit_set import (
                Completed,
                Halted,
                complement_guard,
                partition,
            )

            left_term = self.to_term(owner=f"{operator} left operand")
            right_term = other.to_term(owner=f"{operator} right operand")
            dispatch_raises = atomic(
                "python.binary_dispatch_raises",
                [str_const(operator), left_term, right_term],
            )
            halted_face, completed_face = partition(
                ("binary-native-dispatch", str(site), operator)
            )
            return ExitSet(
                (
                    Halted(
                        dispatch_raises,
                        RaiseEffect(
                            blame=str(site),
                            occurrence=str(site),
                            producer_node_owner="BinOp",
                        ),
                        faces=frozenset({halted_face}),
                    ),
                    Completed(
                        complement_guard(dispatch_raises),
                        SymbolicValue(ctor(operator, [left_term, right_term])),
                        frozenset({completed_face}),
                    ),
                )
            ).normalize()
        return self._binary_floor_gap(
            other,
            site,
            owner,
            f"runtime binary operator {operator}",
        )

    def matrix_multiply(self, other, site):
        return self._runtime_bitwise_dispatch(other, site, "@")

    def unary_plus(self, site):
        # The term does not state a runtime type, so it cannot decide whether
        # ``+`` is identity or raises TypeError (e.g. DatetimeArray).  Completing
        # as the operand erases that exceptional face.
        return super().unary_plus(site)

    def bitwise_invert(self, site):
        # The term does not state a runtime type, so it cannot decide whether
        # ``~`` returns a value or raises TypeError.  A symbolic coordinate for
        # the success face would erase that exceptional face.
        return super().bitwise_invert(site)

    def subscript(self, index, site):
        if self.formal_coordinate is not None:
            from sugar_lift_py_tests.caller_parameter_contract import (
                ContractConditionalConstructionV1,
            )
            from sugar_lift_py_tests.ir import atomic

            built = self.py_subscript_coordinate(index, site)
            return ContractConditionalConstructionV1.mint(
                site=site,
                candidate=built.value.to_term(owner=str(site)),
                demand_formula=atomic("python:indexable", [self.term]),
                value=built.value,
                coordinate=self.formal_coordinate,
            )
        return self.undecided_subscript(
            index,
            site,
            owner="SymbolicValue.subscript",
        )

    def attribute(self, name, site):
        return self.undecided_attribute(name, site, owner="SymbolicValue.attribute")

    def contains(self, item, site):
        # `item in self`: a symbolic container stays the py.in coordinate, a
        # boolean-valued opaque predicate (`item in recv`). Membership on an
        # unknown container is uninterpreted -- decidable only where a later
        # equality/guard consumes it, never invented.
        del site
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.ir import atomic
        from sugar_lift_py_tests.outcome import Complete

        return Complete(
            PredicateValue(atomic("py.in", [item.to_term(owner="contains"), self.term]))
        )

    def format_data_model(self, spec, site, ctx):
        """Construct ``format(symbolic, spec)`` as an exact data-model coordinate.

        A free/opaque receiver has no diggable ``__format__`` body. The spelling
        is still decidable: name the ``call:__format__(receiver, spec)`` method
        coordinate without inventing a concrete return string (#5156).
        """
        del ctx
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.outcome import Complete

        return Complete(
            CallSiteValue(
                target_name="__format__",
                arg_values=(self, spec),
                parameters=(),
                term=ctor(
                    "call:__format__",
                    [
                        self.to_term(owner=str(site)),
                        spec.to_term(owner=str(site)),
                    ],
                    symbol_kind="method-coordinate",
                ),
                body=None,
                site=site,
            )
        )

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
        if (
            operation.name
            in {
                "__repr__",
                "__bytes__",
                "__abs__",
                "__float__",
                "__complex__",
                "__index__",
                "__round__",
                "__floor__",
                "__ceil__",
                "__trunc__",
            }
            and not operation.arguments
        ):
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
        from sugar_lift_py_tests.gap.panic import construction_panic_gap
        from sugar_lift_py_tests.outcome import Incomplete

        construction_panic_gap(
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
        from sugar_lift_py_tests.effect import (
            MapReceiverRuntimeEffect,
            runtime_effect_evidence,
        )
        from sugar_lift_py_tests.outcome import Incomplete

        return Incomplete(
            MapReceiverRuntimeEffect(
                "map receiver runtime boundary: SymbolicValue.map depends on "
                "the receiver's runtime collection semantics and pandas mapping "
                "rules; keep as typed red until a narrower symbolic map floor "
                f"owns this shape. blame={operation.blame}",
                **runtime_effect_evidence("py.map", self.term, operation),
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
        from sugar_lift_py_tests.effect import (
            AsyncIterationRuntimeEffect,
            runtime_effect_evidence,
        )
        from sugar_lift_py_tests.outcome import Incomplete

        return Incomplete(
            AsyncIterationRuntimeEffect(
                "async for runtime boundary: symbolic iterable cannot be "
                "async-iterated without a concrete async-iterator floor; "
                f"owner={operation.owner}; keep as typed red until a narrower "
                f"async-iter floor owns this shape. blame={operation.blame}",
                **runtime_effect_evidence("py.async_iter", self.term, operation),
            )
        )

    def await_with(self, operation, ctx):
        """await on a free/symbolic awaitable — typed red, not floor panic."""
        del ctx
        from sugar_lift_py_tests.effect import (
            AwaitRuntimeEffect,
            runtime_effect_evidence,
        )
        from sugar_lift_py_tests.outcome import Incomplete

        return Incomplete(
            AwaitRuntimeEffect(
                "await runtime boundary: symbolic awaitable cannot be forced "
                "without a concrete awaitable floor; "
                f"owner={operation.owner}; keep as typed red until a narrower "
                f"await floor owns this shape. blame={operation.blame}",
                **runtime_effect_evidence("py.await", self.term, operation),
            )
        )

    def async_context_manager_with(self, operation, ctx):
        """async with over a free/symbolic manager — typed red, not floor panic."""
        del ctx
        from sugar_lift_py_tests.effect import (
            AsyncContextManagerRuntimeEffect,
            runtime_effect_evidence,
        )
        from sugar_lift_py_tests.outcome import Incomplete

        return Incomplete(
            AsyncContextManagerRuntimeEffect(
                "async with runtime boundary: symbolic manager cannot enter "
                "an async context without a concrete async-CM floor; "
                f"owner={operation.owner}; keep as typed red until a narrower "
                f"async-with floor owns this shape. blame={operation.blame}",
                **runtime_effect_evidence("py.async_with", self.term, operation),
            )
        )

    def attribute_assign_with(self, operation, ctx):
        del ctx
        from sugar_lift_py_tests.effect import (
            AttributeStoreRuntimeEffect,
            runtime_effect_evidence,
        )
        from sugar_lift_py_tests.outcome import Incomplete

        return Incomplete(
            AttributeStoreRuntimeEffect(
                "attribute assignment runtime boundary: symbolic receiver "
                f"`{self.term}` cannot be mutated as source object state. "
                "Python attribute assignment can invoke descriptors and "
                "__setattr__ at runtime; keep as typed red until a narrower "
                "attribute mutation floor owns this shape. "
                f"blame={operation.blame}",
                **runtime_effect_evidence("py.setattr", self.term, operation),
            )
        )

    def setitem_with(self, operation, ctx):
        """Rebind a symbolic mapping/list coordinate after a store.

        No element history exists to fold, but a name-bound store still has a
        post-state: carry prior coordinate, index, and value on ``py.setitem``.
        """
        del ctx
        return self.setitem(operation.index, operation.value, operation.blame)

    def setitem(self, index, value, site):
        """Rebind a symbolic container after ``xs[k] = v``.

        Concrete containers fold post-state. A symbolic formal (for example
        ``**kwargs``) has no element history, but the assignment still rebinds
        the name: carry prior coordinate, index, and value on ``py.setitem``.
        Do not invent members; do not hide the gap — silence stays illegal.
        """
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.outcome import Complete
        from sugar_lift_py_tests.sugar.floor_terms import floor_to_term

        index_term = floor_to_term(index, owner="SymbolicValue.setitem index")
        value_term = floor_to_term(value, owner="SymbolicValue.setitem value")
        return Complete(
            CallSiteValue(
                target_name="setitem",
                arg_values=(self, index, value),
                parameters=(),
                term=ctor(
                    "py.setitem",
                    [self.to_term(owner=str(site)), index_term, value_term],
                    symbol_kind="method-coordinate",
                ),
                body=None,
                site=site,
            )
        )

    def delitem(self, index, site):
        """Rebind a symbolic container after ``del xs[k]``.

        A symbolic receiver has no element history to fold, but deletion still
        constructs a post-state. Carry that state as the same ``py.delitem``
        coordinate used for opaque callsite receivers.
        """
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.outcome import Complete
        from sugar_lift_py_tests.sugar.floor_terms import floor_to_term

        index_term = floor_to_term(index, owner="SymbolicValue.delitem index")
        return Complete(
            CallSiteValue(
                target_name="delitem",
                arg_values=(self, index),
                parameters=(),
                term=ctor(
                    "py.delitem",
                    [self.to_term(owner=str(site)), index_term],
                    symbol_kind="method-coordinate",
                ),
                body=None,
                site=site,
            )
        )
