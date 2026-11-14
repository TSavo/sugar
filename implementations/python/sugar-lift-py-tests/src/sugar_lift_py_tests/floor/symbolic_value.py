from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.call_symbol import call_symbol
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
        from sugar_lift_py_tests.outcome import ExitSet
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
        from sugar_lift_py_tests.floor.python_type_coordinate import (
            authenticated_python_type_spelling,
        )

        del type_name  # display spelling is not authority
        authenticated = authenticated_python_type_spelling(
            type_term, owner="SymbolicValue.python_isinstance", site=site
        )
        term = self.term
        if type(term) is _Ctor and term.name in ground_type_names:
            matches = ground_type_names[term.name] == authenticated
            return ExitSet.completed(
                TrueBoolLiteralSugar(site=site)
                if matches
                else FalseBoolLiteralSugar(site=site)
            )
        return super().python_isinstance(authenticated, type_term, site)

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
        from sugar_lift_py_tests.outcome import ExitSet

        operation = ctor(
            "adt.is_python_type",
            [value.to_term(owner="isinstance value"), term],
        )
        return ExitSet.halted(
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
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.completed(
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
        if self.formal_coordinate is not None:
            from sugar_lift_py_tests.caller_parameter_contract import (
                NativeOperationExitCarrierV1,
            )

            return NativeOperationExitCarrierV1.mint(
                site=site,
                operator="truth",
                operands=(self,),
                coordinates=(self.formal_coordinate,),
            )
        # A symbolic value EMITS the Python truth relation; the sort adjudicates later.
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.ir import py_truthy
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.completed(PredicateValue(py_truthy(self.term), site))

    def guarded(self, formula):
        """Keep one symbolic value coordinate unchanged beneath control.

        A bare symbolic value is support, not a branch-local binding or a fact:
        it contributes no invariant/postcondition and has no absent peer from
        which a ``GuardedValue`` could be constructed.  The enclosing ExitSet
        owns the control guard.  Changing this value's term would instead mint
        a second identity for the same source value under another path.
        """
        del formula
        return self

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
            from sugar_lift_py_tests.outcome import ExitSet
            from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
                FalseBoolLiteralSugar,
            )
            from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
                TrueBoolLiteralSugar,
            )

            return ExitSet.completed(
                TrueBoolLiteralSugar(site=site)
                if left.args[0].value == right.args[0].value
                else FalseBoolLiteralSugar(site=site)
            )
        return super().is_identical(other, site)

    def length(self, site):
        # A symbolic length stays the call:len coordinate -- the vendor's stated address.
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.completed(
            CallSiteValue(
                target_name="len",
                arg_values=(self,),
                parameters=(),
                term=ctor(
                    call_symbol("len"),
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
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.halted(
            AppendRuntimeEffect(
                "append runtime boundary: symbolic receiver has no constructed "
                f"list post-state; value={value.to_term(owner=str(site))!r}; "
                f"site={site}",
                **runtime_effect_evidence("py.append", self, site),
            )
        )

    def unary_minus(self, site):
        # Formal operands: defer to authenticated discharge (same door as
        # truth / binary).  A free/open symbol still cannot invent success vs
        # TypeError — that remains the undecided refusal on the base law.
        if self.formal_coordinate is not None:
            from sugar_lift_py_tests.caller_parameter_contract import (
                NativeOperationExitCarrierV1,
            )

            return NativeOperationExitCarrierV1.mint(
                site=site,
                operator="unary_minus",
                operands=(self,),
                coordinates=(self.formal_coordinate,),
            )
        return super().unary_minus(site)

    def multiply(self, other, site, ctx):
        # Symbolic numeric multiplication keeps the native coordinate. A symbolic
        # value used as a sequence repetition count has not proved Python's
        # __index__ contract, so it must remain a named construction gap.
        from sugar_lift_py_tests.floor.list_value import ListValue

        if type(other) is ListValue:
            return other.multiply(self, site, ctx)

        return self._runtime_binary_dispatch(other, site, ctx, "*")

    def power(self, other, site, ctx):
        return self._runtime_binary_dispatch(other, site, ctx, "**")

    def add(self, other, site, ctx):
        return self._runtime_binary_dispatch(other, site, ctx, "+")

    def subtract(self, other, site, ctx):
        return self._runtime_binary_dispatch(other, site, ctx, "-")

    def divide(self, other, site, ctx):
        return self._arithmetic_dispatch(other, site, ctx, "/")

    def floor_divide(self, other, site, ctx):
        return self._arithmetic_dispatch(other, site, ctx, "//")

    def modulo(self, other, site, ctx):
        return self._arithmetic_dispatch(other, site, ctx, "%")

    def _arithmetic_dispatch(self, other, site, ctx, operator):
        return self._runtime_binary_dispatch(other, site, ctx, operator)

    def right_shift(self, other, site, ctx):
        return self._runtime_binary_dispatch(other, site, ctx, ">>")

    def bitwise_and(self, other, site, ctx):
        return self._runtime_bitwise_dispatch(other, site, ctx, "&")

    def bitwise_xor(self, other, site, ctx):
        return self._runtime_bitwise_dispatch(other, site, ctx, "^")

    def bitwise_or(self, other, site, ctx):
        return self._runtime_bitwise_dispatch(other, site, ctx, "|")

    def left_shift(self, other, site, ctx):
        return self._runtime_bitwise_dispatch(other, site, ctx, "<<")

    def _runtime_bitwise_dispatch(self, other, site, ctx, operator):
        return self._runtime_binary_dispatch(other, site, ctx, operator)

    def _runtime_binary_dispatch(self, other, site, ctx, operator):
        from sugar_lift_py_tests.floor.guarded_value import GuardedValue
        from sugar_lift_py_tests.floor.string_value import StringValue

        owner = next(
            method
            for method, coordinate in _BINARY_OPERATOR_COORDINATE.items()
            if coordinate == operator
        )
        left_coordinate = self.formal_coordinate
        right_coordinate = getattr(other, "formal_coordinate", None)
        if left_coordinate is not None or right_coordinate is not None:
            from sugar_lift_py_tests.caller_parameter_contract import (
                NativeOperationExitCarrierV1,
            )

            return NativeOperationExitCarrierV1.mint(
                site=site,
                operator=owner,
                operands=(self, other),
                coordinates=(left_coordinate, right_coordinate),
            )
        # Symbolic + str concat without a seated formal (NameSugar desugar of a
        # parameter before FormalRef seating) used to SNW at
        # binary_operation_exception_floor — enum.py:75 ``cls_name + '.' + …``.
        # That abort escaped through dependency ClassDef/function force-floor
        # during MaterializeModule of pandas files (e.g. io/json/_json.py) and
        # returned functionsTotal=0 before any function walk. Mint the same
        # native-operation ExitSet carrier formals already use; coordinates may
        # be None. Do not invent ExitSet.completed(SymbolicValue) concat
        # (undecided-law).
        if operator == "+" and type(other) is StringValue:
            from sugar_lift_py_tests.caller_parameter_contract import (
                NativeOperationExitCarrierV1,
            )

            return NativeOperationExitCarrierV1.mint(
                site=site,
                operator=owner,
                operands=(self, other),
                coordinates=(left_coordinate, right_coordinate),
            )
        if isinstance(other, GuardedValue):
            return other.map_from_left(owner, self, site, ctx)
        # Undecided native dispatch: the shared law's two faces (completes
        # under python:binary_op.completes, else an UndeterminedRaiseEffect).
        # Never a sole ExitSet.completed(SymbolicValue): that claims it cannot raise.
        refused = self._undecided_binary_law(other, site, operator)
        if refused is not None:
            return refused
        return self._binary_floor_gap(
            other,
            site,
            owner,
            f"runtime binary operator {operator}",
        )

    def matrix_multiply(self, other, site, ctx):
        return self._runtime_bitwise_dispatch(other, site, ctx, "@")

    def unary_plus(self, site):
        # Formal operands: authenticated discharge.  Open symbols stay refused
        # (success vs TypeError is not source-decidable without a type).
        if self.formal_coordinate is not None:
            from sugar_lift_py_tests.caller_parameter_contract import (
                NativeOperationExitCarrierV1,
            )

            return NativeOperationExitCarrierV1.mint(
                site=site,
                operator="unary_plus",
                operands=(self,),
                coordinates=(self.formal_coordinate,),
            )
        return super().unary_plus(site)

    def bitwise_invert(self, site):
        # Formal operands: authenticated discharge.  Open symbols stay refused.
        if self.formal_coordinate is not None:
            from sugar_lift_py_tests.caller_parameter_contract import (
                NativeOperationExitCarrierV1,
            )

            return NativeOperationExitCarrierV1.mint(
                site=site,
                operator="bitwise_invert",
                operands=(self,),
                coordinates=(self.formal_coordinate,),
            )
        return super().bitwise_invert(site)

    def subscript(self, index, site):
        # A parameter in either operand defers to the caller's actual: the
        # one ``subscript`` mint (``defer_formal_subscript``).
        from sugar_lift_py_tests.operations.subscript_operation import (
            defer_formal_subscript,
        )

        deferred = defer_formal_subscript(self, index, site)
        if deferred is not None:
            return deferred
        return self.undecided_subscript(
            index,
            site,
            owner="SymbolicValue.subscript",
        )

    def attribute(self, name, site, ctx):
        """Name ``__name__`` / ``__qualname__`` as a coordinate, without inventing the string.

        RaisesExc's absent-effect diagnostic formats
        ``self.expected_exceptions[0].__name__``. A class actual already
        exposes the authenticated type name. When that element is the
        constructor formal, guessing AttributeError or inventing a concrete
        type name is dishonest. The spelling is still decidable: emit
        ``attr:__name__(receiver)`` the same way ``format_data_model`` names
        ``call:__format__`` without inventing the formatted string.
        """
        if name in {"__name__", "__qualname__"}:
            from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
            from sugar_lift_py_tests.ir import ctor
            from sugar_lift_py_tests.outcome import ExitSet

            return ExitSet.completed(
                CallSiteValue(
                    target_name=name,
                    arg_values=(self,),
                    parameters=(),
                    term=ctor(
                        f"attr:{name}",
                        [self.to_term(owner=str(site))],
                        symbol_kind="method-coordinate",
                    ),
                    body=None,
                    site=site,
                    type_name_attribute=True,
                )
            )
        return self.undecided_attribute(name, site, owner="SymbolicValue.attribute")

    def contains(self, item, site):
        # Membership on an unknown container is a third value: neither
        # ExitSet.completed(py.in) nor TypeError is honest without container-type
        # testimony. Named refusal, not fabrication.
        return self.undecided_contains(item, site, owner="SymbolicValue.contains")

    def format_data_model(self, spec, site, ctx):
        """Construct ``format(symbolic, spec)`` as an exact data-model coordinate.

        A free/opaque receiver has no diggable ``__format__`` body. The spelling
        is still decidable: name the ``call:__format__(receiver, spec)`` method
        coordinate without inventing a concrete return string (#5156).
        """
        del ctx
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.completed(
            CallSiteValue(
                target_name="__format__",
                arg_values=(self, spec),
                parameters=(),
                term=ctor(
                    call_symbol("__format__"),
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

    def subscript_with(self, operation, ctx):
        """``symbolic[k]`` from source answers through :meth:`subscript`.

        A formal receiver's subscript is decided by its caller's actual at the
        call: the ``subscript`` carrier, discharged through the one subscript
        door (as a formal's ``obj[k] += v``, store, delete and attribute read
        already are).  Any other symbolic receiver is the one undecided read:
        both faces, one debt (:meth:`undecided_subscript`).
        """
        del ctx
        return self.subscript(operation.index, operation.blame)

    def iter_with(self, operation, ctx):
        """``iter(symbolic)``.

        A formal's ``iter`` is decided by its caller's actual: the ``iter``
        carrier, discharged through ``project_iter`` (as every other
        operation on a formal is).  Any other symbolic receiver's
        ``__iter__`` is not decided here, so the call is the one two-faced
        unanswered outcome (:meth:`undecided_iteration`).  A live ``for``
        over a symbolic iterable never submits this operation: it is the
        loop's recurrence."""
        del ctx
        if self.formal_coordinate is not None:
            from sugar_lift_py_tests.caller_parameter_contract import (
                NativeOperationExitCarrierV1,
            )

            return NativeOperationExitCarrierV1.mint(
                site=operation.blame,
                operator="iter",
                operands=(self,),
                coordinates=(self.formal_coordinate,),
            )
        return self.undecided_iteration(operation.blame, owner="SymbolicValue.iter")

    def next_with(self, operation, ctx):
        """``next(symbolic)``.

        A formal's ``next`` is decided by its caller's actual: the ``next``
        carrier, discharged through ``project_next``.  Any other symbolic
        receiver's ``__next__`` is not decided here, so the call is the one
        two-faced unanswered outcome (:meth:`undecided_next`)."""
        del ctx
        if self.formal_coordinate is not None:
            from sugar_lift_py_tests.caller_parameter_contract import (
                NativeOperationExitCarrierV1,
            )

            return NativeOperationExitCarrierV1.mint(
                site=operation.blame,
                operator="next",
                operands=(self,),
                coordinates=(self.formal_coordinate,),
            )
        return self.undecided_next(operation.blame, owner="SymbolicValue.next")

    def project_sequence_with(self, operation, ctx):
        return operation.project_symbolic(self, ctx)

    def setitem(self, index, value, site, ctx):
        """Rebind a symbolic container after ``xs[k] = v``.

        Concrete containers fold post-state. A symbolic formal (for example
        ``**kwargs``) has no element history, but the assignment still rebinds
        the name: carry prior coordinate, index, and value on ``py.setitem``.
        Do not invent members; do not hide the gap — silence stays illegal.
        """
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.outcome import ExitSet

        index_term = index.to_term(owner="SymbolicValue.setitem index")
        value_term = value.to_term(owner="SymbolicValue.setitem value")
        return ExitSet.completed(
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

    def delitem(self, index, site, ctx):
        """Rebind a symbolic container after ``del xs[k]``.

        A symbolic receiver has no element history to fold, but deletion still
        constructs a post-state. Carry that state as the same ``py.delitem``
        coordinate used for opaque callsite receivers.
        """
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.outcome import ExitSet

        index_term = index.to_term(owner="SymbolicValue.delitem index")
        return ExitSet.completed(
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
