from __future__ import annotations

from dataclasses import dataclass, field

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
    # A comprehension's symbolic member, as the comprehension binds it before
    # any read (``ComprehensionSugar._symbolic_member``): the member ``next``
    # yielded, and each leaf's projection of it.  Nothing binds it and no
    # input decides it, so a read of it owes the
    # undecided member (``loop_recurrence_sugar.holds_recurrence_value``,
    # #7757).  So does its final member, what a lambda made in the
    # comprehension reads after it (``ComprehensionSugar._symbolic_final_ctx``,
    # ``python:comprehension.final_member``).  Not part of the value's
    # identity.
    recurrence_member: bool = field(default=False, compare=False)

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
        """``bool(self)`` asked of the value itself: the one truth rule's
        two faces (``bool_op_sugar._unanswered_truth``), a formal's or not.

        Nothing decides this value's type, so its ``__bool__`` / ``__len__``
        is a protocol with a fallback that no one dispatched method states:
        it completes with ``python:truth_result(<term>, <key>)`` under
        ``python:truth.completes`` and halts undetermined under the
        complement, owed either way (#7757 NEW-1, NEW-5).  This is what
        ``truth_of`` answers for it, so a direct ``.truth`` caller
        (``predicate_formula``, a ``match`` guard) cannot read a halt-less
        truth.  It waits on no caller's actual: a caller's actual joined on a
        formal at prove decides the completes atom where its type is a
        builtin's."""
        from sugar_lift_py_tests.sugar.bool_op_sugar import _unanswered_truth

        return _unanswered_truth(self, site, owner="SymbolicValue.truth")

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
        # A formal operand: ``-p`` is the undecided two faces (#7757 NEW-1),
        # owed, its halt kept -- no single dunder prove states decides it for
        # a class nothing here decided.  A free/open symbol still cannot
        # invent success vs TypeError: the undecided refusal on the base law.
        if self.formal_coordinate is not None:
            return self.undecided_unary("-", site, owner="SymbolicValue.unary_minus")
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

        owner = next(
            method
            for method, coordinate in _BINARY_OPERATOR_COORDINATE.items()
            if coordinate == operator
        )
        # A parameter operand, on either side, is not deferred to a caller:
        # a binary operator is a protocol with a fallback (``__op__``, then
        # the reflected ``__rop__`` after ``NotImplemented``, the subclass
        # rule first), which no one dispatched method states.  So whether or
        # not the parameter's class is an input, ``p + q`` takes the one
        # undecided binary law below, like every other undecided pair: it
        # completes under its own atom and owes the undecided member, or
        # raises something undetermined (#7757, audit row NEW-1).
        if isinstance(other, GuardedValue):
            from sugar_lift_py_tests.floor.floor_value import BINARY_FLOOR_OPERATIONS

            operate = BINARY_FLOOR_OPERATIONS[owner]
            return other.map_from_left(
                lambda arm: operate(self, arm, site, ctx), site, operation=owner
            )
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
        # A formal operand: ``+p`` is the undecided two faces (#7757 NEW-1),
        # owed, its halt kept -- no single dunder prove states decides it for
        # a class nothing here decided.  A free/open symbol still cannot
        # invent success vs TypeError: the undecided refusal on the base law.
        if self.formal_coordinate is not None:
            return self.undecided_unary("+", site, owner="SymbolicValue.unary_plus")
        return super().unary_plus(site)

    def bitwise_invert(self, site):
        # A formal operand: ``~p`` is the undecided two faces (#7757 NEW-1),
        # owed, its halt kept -- no single dunder prove states decides it for
        # a class nothing here decided.  A free/open symbol still cannot
        # invent success vs TypeError: the undecided refusal on the base law.
        if self.formal_coordinate is not None:
            return self.undecided_unary("~", site, owner="SymbolicValue.bitwise_invert")
        return super().bitwise_invert(site)

    def subscript(self, index, site):
        # Nothing here decides a symbolic receiver's type or its
        # ``__getitem__`` -- a parameter's (``p[k]``, ``p[a:b]``) included --
        # so the read is the one undecided read: both faces, owed.  No read
        # waits on a caller's actual (#7757).
        return self.undecided_subscript(
            index,
            site,
            owner="SymbolicValue.subscript",
        )

    def attribute(self, name, site, ctx):
        """``self.name``: the one two-faced undecided read
        (``undecided_attribute``), whatever bound the receiver -- a formal, a
        free name, a module alias with no member receipt (``import sys``;
        ``sys.maxsize``).  Nothing here decides the receiver's runtime type or
        its ``__getattribute__``, so every member may raise.

        ``__name__`` / ``__qualname__`` complete as a coordinate, without
        inventing the string: RaisesExc's absent-effect diagnostic formats
        ``self.expected_exceptions[0].__name__``, and guessing a concrete type
        name is dishonest.  The spelling is still decidable: the completed
        face is ``attr:__name__(receiver)``, marked as the type-name read
        (``type_name_attribute``), the same way ``format_data_model`` names
        ``call:__format__`` without inventing the formatted string.  It keeps
        the read's raise face: an object need not have a ``__name__``.

        On an input of the function whose own proof this is (a parameter, a
        captured cell: ``formal_coordinate``) the undecided read is keyed per
        evaluation (``floor_value.undecided_attribute_result``): two reads
        of one parameter are two values (#7757).
        """
        if self.formal_coordinate is not None:
            from sugar_lift_py_tests.floor.floor_value import (
                undecided_attribute_result,
            )

            outcome = undecided_attribute_result(
                self, name, site, owner="SymbolicValue.attribute"
            )
        else:
            outcome = self.undecided_attribute(
                name, site, owner="SymbolicValue.attribute"
            )
        if name not in {"__name__", "__qualname__"}:
            return outcome
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.outcome import ExitSet

        type_name = CallSiteValue(
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
        return outcome.and_then(lambda _member: ExitSet.completed(type_name))

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

        Every symbolic receiver, a formal's included, is the one undecided
        read: both faces, one debt (:meth:`undecided_subscript`).  A formal
        read by an item read has no class input
        (``nodes._receiver_class_parameters`` counts the read as a bare one),
        so there is no dispatched ``__getitem__`` to make.
        """
        del ctx
        return self.subscript(operation.index, operation.blame)

    def iter_with(self, operation, ctx):
        """``iter(symbolic)``.

        A symbolic receiver's ``__iter__`` is not decided here -- a formal's
        included: iteration is ``__iter__`` then the ``__getitem__`` sequence
        protocol, a fallback no one dispatched method states (#7757 NEW-1) --
        so the call is the one two-faced unanswered outcome
        (:meth:`undecided_iteration`), owed, its halt kept.  A ``for`` over a
        symbolic iterable submits this operation too: the loop's recurrence
        is what follows the face it completes on
        (``LoopRecurrenceSugar._desugar_with_iterable``)."""
        del ctx
        return self.undecided_iteration(operation.blame, owner="SymbolicValue.iter")

    def next_with(self, operation, ctx):
        """``next(symbolic)``.

        A symbolic receiver's ``__next__`` is not decided here, a formal's
        included (#7757 NEW-1), so the call is the one two-faced unanswered
        outcome (:meth:`undecided_next`), owed, its halt kept."""
        del ctx
        return self.undecided_next(operation.blame, owner="SymbolicValue.next")

    def project_sequence_with(self, operation, ctx):
        return operation.project_symbolic(self, ctx)

    # No ``setitem``/``delitem`` here: a symbolic receiver's type is not
    # decided, so its item store or delete is the one item mutation's
    # undecided arm (``store_effect_sugar.item_mutation``: completes under
    # its own atom or raises something undetermined, owed), or its
    # dispatched edge where its class is an input.  A path that reaches the
    # floor's own method instead refuses by name (``FloorValue.setitem``),
    # never completes with the halt dropped (#7757 step 7).
