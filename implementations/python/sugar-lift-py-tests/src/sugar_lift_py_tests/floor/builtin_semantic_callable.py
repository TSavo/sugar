from __future__ import annotations

from dataclasses import dataclass, field

from .closed_operation_witness import (
    ClosedSemanticOperationWitness,
    PythonRuntimeIdentity,
)
from .floor_value import FloorValue


@dataclass(frozen=True)
class BuiltinSemanticCallable(FloorValue):
    operation: str
    runtime_identity: PythonRuntimeIdentity = field(
        default_factory=PythonRuntimeIdentity.current
    )

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:builtin_semantic_callable",
            [
                str_const(self.runtime_identity.implementation),
                str_const(
                    f"{self.runtime_identity.major}.{self.runtime_identity.minor}"
                ),
                str_const(self.operation),
            ],
            symbol_kind="builtin",
        )

    def callable_application_with(self, operation, ctx):
        from sugar_source_tree.nodes import LanguageCallee

        if self.operation == "python.set.construct":
            floored = self._construct_set(operation)
            if floored is not None:
                return floored
            return self._unhandled_construct(
                operation, "set", LanguageCallee.BUILTIN_SET
            )
        if self.operation == "python.tuple.construct":
            floored = self._construct_tuple(operation)
            if floored is not None:
                return floored
            return self._unhandled_construct(
                operation, "tuple", LanguageCallee.BUILTIN_TUPLE
            )
        if self.operation == "python.dict.construct":
            floored = self._construct_dict(operation)
            if floored is not None:
                return floored
            return self._unhandled_construct(
                operation, "dict", LanguageCallee.BUILTIN_DICT
            )
        if self.operation in (
            "python.re.search",
            "python.re.match",
            "python.re.fullmatch",
        ):
            return self._re_match(operation)
        if self.operation == "python.isinstance":
            return self._isinstance(operation)
        if self.operation == "python.len":
            return self._len(operation)
        if self.operation == "python.enumerate.construct":
            return self._enumerate(operation, ctx)
        if self.operation == "python.super.construct":
            if operation.arguments or operation.keyword_names:
                return super().callable_application_with(operation, ctx)
            from sugar_lift_py_tests.floor.builtin_super_value import BuiltinSuperValue
            from sugar_lift_py_tests.outcome import ExitSet

            current_class = ctx.temporal.value_if_bound("__class__")
            receiver = next(
                (
                    ctx.temporal.value_if_bound(name)
                    for name in ("self", "metacls", "cls")
                    if ctx.temporal.value_if_bound(name) is not None
                ),
                None,
            )
            if current_class is None or receiver is None:
                from sugar_lift_py_tests.gap.panic import construction_panic_gap

                construction_panic_gap(
                    owner="BuiltinSemanticCallable.python.super",
                    blame=str(operation.site),
                    observed="missing __class__ cell or first formal receiver",
                    requested="authenticated zero-argument super context",
                    fix="carry the defining class and bound first formal into the method body",
                )
            return ExitSet.completed(
                BuiltinSuperValue(current_class=current_class, receiver=receiver)
            )
        if self.operation != "python.issubclass":
            return super().callable_application_with(operation, ctx)
        if len(operation.arguments) != 2 or operation.keyword_names:
            from sugar_lift_py_tests.gap.panic import construction_panic_gap

            construction_panic_gap(
                owner="BuiltinSemanticCallable.python.issubclass",
                blame=str(operation.site),
                observed=(len(operation.arguments), operation.keyword_names),
                requested="exactly two positional authenticated type operands",
                fix="construct Python issubclass arity exactly or keep it loud",
            )
        subtype, supertype = operation.arguments
        subtype = self._resolve_type_operand(subtype, operation.site, 0)
        supertype = self._resolve_type_operand(supertype, operation.site, 1)
        test = getattr(subtype, "test_python_subtype", None)
        if test is None:
            # No floor testifies what this operand is as a class (a call
            # result nobody looked at): neither answer nor CPython's
            # TypeError for a non-class is honest yet.
            from sugar_source_tree.panic import SugarNotWritten

            raise SugarNotWritten(
                blame=operation.site,
                owner="BuiltinSemanticCallable.python.issubclass",
                observed=(
                    "issubclass operand without class testimony: "
                    f"{type(subtype).__name__}"
                ),
                requested="an authenticated class operand",
                fix="carry the operand's class identity, or keep the call loud",
            )
        return test(supertype, operation.site)

    def _unhandled_construct(self, operation, name: str, language_callee):
        """A construction no floor decided: the bodiless call, with its raise.

        ``tuple(opaque_genexp)`` must remain a CallSiteValue coordinate so later
        force_floor / field projection can refuse with a stage-keyed residual
        rather than aborting the whole manager factory membrane. The
        coordinate carries the ``LanguageCallee`` this builtin binding is, so
        a reader asks the binding, never the spelling ``name`` (#7757).

        Constructing ``set``/``tuple``/``dict`` iterates the operand (its
        ``__iter__`` and, for ``set``/``dict``, its members' ``__hash__``/
        ``__eq__``), which may raise; the call completes outright only on a
        shape ``builtin_call_total`` lists.  Otherwise it is the law the
        frameless builtin call reads (``builtin_dunder_call``: the one
        unanswered call for a dunder not CPython's own, or a decided operand
        CPython may still refuse), else the one unanswered call
        (``UnknownCalleeCallV1``): two-faced, its completed face this
        coordinate (#7757: a halt is never dropped).
        """
        from sugar_lift_py_tests.call_symbol import call_symbol
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.outcome import ExitSet
        from sugar_lift_py_tests.source_call_resolution import (
            UnknownCalleeCallV1,
            builtin_call_total,
            builtin_dunder_call,
        )

        args = operation.arguments
        keyword_names = tuple(operation.keyword_names or ())
        owner = str(operation.site)
        callsite = CallSiteValue(
            target_name=name,
            arg_values=args,
            parameters=(),
            term=ctor(
                call_symbol(name),
                [value.to_term(owner=owner) for value in args],
                symbol_kind="builtin",
            ),
            body=None,
            site=operation.site,
            language_callee=language_callee,
        )
        if builtin_call_total(language_callee, args, keyword_names):
            return ExitSet.completed(callsite)
        unanswered = builtin_dunder_call(language_callee, args, keyword_names)
        if unanswered is None:
            unanswered = UnknownCalleeCallV1(name)
        return unanswered.faces(callsite, operation.site)

    def _len(self, operation):
        """Exact ``len(container)`` over floors that already know their size."""
        if operation.keyword_names or len(operation.arguments) != 1:
            from sugar_lift_py_tests.gap.panic import construction_panic_gap

            construction_panic_gap(
                owner="BuiltinSemanticCallable.python.len",
                blame=str(operation.site),
                observed=(len(operation.arguments), operation.keyword_names),
                requested="exactly one positional authenticated len operand",
                fix="construct Python len arity exactly or keep it loud",
            )
        container = operation.arguments[0]
        length = getattr(container, "length", None)
        if not callable(length):
            from sugar_lift_py_tests.gap.panic import construction_panic_gap

            construction_panic_gap(
                owner="BuiltinSemanticCallable.python.len",
                blame=str(operation.site),
                observed=type(container).__name__,
                requested="container floor with source-visible length",
                fix="project finite containers before len or keep the call loud",
            )
        return length(operation.site)

    def _enumerate(self, operation, ctx):
        """Construct the exact finite iterator for an authenticated sequence."""
        if operation.keyword_names or len(operation.arguments) != 1:
            return super().callable_application_with(operation, ctx)
        from sugar_lift_py_tests.floor import (
            ComprehensionValue,
            ListIteratorValue,
            ListValue,
            TermValue,
            TupleValue,
        )
        from sugar_lift_py_tests.outcome import ExitSet

        source = operation.arguments[0]
        if isinstance(source, (ListValue, TupleValue)):
            elements = source.elements
        elif (
            isinstance(source, ComprehensionValue)
            and source.finite_elements is not None
        ):
            elements = source.finite_elements
        else:
            return super().callable_application_with(operation, ctx)
        return ExitSet.completed(
            ListIteratorValue(
                tuple(
                    TupleValue((TermValue(index), value))
                    for index, value in enumerate(elements)
                )
            )
        )

    def _re_match(self, operation):
        """``re.search``/``re.match``/``re.fullmatch`` over the decidable subset.

        Plan Cut 2: language-owned C-floor semantics. Both operands must be
        concrete ``str`` floors; the pattern must be in the decidable subset
        (validate_pattern is the authority). A successful match is a truthy
        ``ReMatchValue``; no match is ``NoneValue``. Symbolic operands or a
        pattern outside the subset keep the call loud -- never a guessed
        match or non-match.
        """
        from sugar_lift_py_tests.floor.none_value import NoneValue
        from sugar_lift_py_tests.floor.re_match_value import ReMatchValue
        from sugar_lift_py_tests.floor.re_subset_matcher import (
            UnsupportedRegexInput,
            UnsupportedRegexPattern,
            re_fullmatch,
            re_match,
            re_search,
        )
        from sugar_lift_py_tests.floor.string_value import StringValue
        from sugar_lift_py_tests.gap.panic import construction_panic_gap
        from sugar_lift_py_tests.outcome import ExitSet

        owner = f"BuiltinSemanticCallable.{self.operation}"
        if operation.keyword_names or len(operation.arguments) != 2:
            construction_panic_gap(
                owner=owner,
                blame=str(operation.site),
                observed=(len(operation.arguments), operation.keyword_names),
                requested="exactly two positional authenticated re operands",
                fix="construct re.search/match/fullmatch arity exactly or keep it loud",
            )
        pattern_v, subject_v = operation.arguments
        if not isinstance(pattern_v, StringValue) or not isinstance(
            subject_v, StringValue
        ):
            construction_panic_gap(
                owner=owner,
                blame=str(operation.site),
                observed=(type(pattern_v).__name__, type(subject_v).__name__),
                requested="concrete str pattern and subject",
                fix=(
                    "keep re over a symbolic pattern/subject loud; only concrete "
                    "operands are decided by the subset matcher"
                ),
            )
        matcher = {
            "python.re.search": re_search,
            "python.re.match": re_match,
            "python.re.fullmatch": re_fullmatch,
        }[self.operation]
        try:
            span = matcher(pattern_v.value, subject_v.value)
        except (UnsupportedRegexPattern, UnsupportedRegexInput) as exc:
            construction_panic_gap(
                owner=owner,
                blame=str(operation.site),
                observed=str(exc),
                requested="a pattern in the decidable re subset",
                fix="keep the call loud until the subset covers this pattern",
            )
        if span is None:
            return ExitSet.completed(NoneValue())
        return ExitSet.completed(ReMatchValue(subject=subject_v.value, span=span))

    def _isinstance(self, operation):
        """Exact ``isinstance(obj, classinfo)`` over authenticated floors.

        ``classinfo`` is a type coordinate or a finite tuple of them. The type
        owns the test via ``test_python_type``; the object answers through
        ``python_isinstance``. Dual-mode EffectBoundary factories (RaisesExc)
        gate ``expected_exceptions`` on ``isinstance(x, tuple)`` — without this
        arm the condition stays a bodyless CallSiteValue and ``not`` refuses.
        """
        if len(operation.arguments) != 2 or operation.keyword_names:
            from sugar_lift_py_tests.gap.panic import construction_panic_gap

            construction_panic_gap(
                owner="BuiltinSemanticCallable.python.isinstance",
                blame=str(operation.site),
                observed=(len(operation.arguments), operation.keyword_names),
                requested="exactly two positional authenticated isinstance operands",
                fix="construct Python isinstance arity exactly or keep it loud",
            )
        obj, classinfo = operation.arguments
        classinfo = self._resolve_type_operand(classinfo, operation.site, 1)
        return classinfo.test_python_type(obj, operation.site)

    def _resolve_type_operand(self, classinfo, site, position):
        """A free name operand read as the builtin class its binding names.

        NameSugar leaves a name no temporal binds as ``SymbolicValue(_Var(
        name))``.  It is the builtin floor's class (``tuple``, ``type``,
        ``BaseException``) only when the call's ``position``-th actual is that
        bare name and its read at its own coordinate falls through to the
        builtin namespace (``SourceUnit.builtin_reference_at``): the spelling
        is never looked up, so a name a star import, a rebinding or a
        parameter may bind stays the free operand it is.
        """
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
        from sugar_lift_py_tests.ir import _Var
        from sugar_source_tree.nodes import Name

        if not isinstance(classinfo, SymbolicValue):
            return classinfo
        term = classinfo.term
        if not isinstance(term, _Var):
            return classinfo
        unit = getattr(site, "unit", None)
        actuals = tuple(getattr(getattr(site, "node", None), "args", None) or ())
        if unit is None or len(actuals) != 2:
            return classinfo
        actual = actuals[position]
        if not isinstance(actual, Name) or actual.id != term.name:
            return classinfo
        target = unit.builtin_reference_at(actual.id, actual.line_col_span())
        if target is None:
            return classinfo
        from sugar_lift_py_tests.temporal.builtin_name_bindings import (
            builtin_name_temporal,
        )

        bound = builtin_name_temporal().value_if_bound(
            target[len("python:builtins.") :]
        )
        return classinfo if bound is None else bound

    def _construct_set(self, operation):
        """``set(iterable)`` over decided members: CPython hashes each member
        in order, keeps the first of equal members, and raises ``TypeError`` at
        the first unhashable one.  A member whose hash or equality the floor
        does not decide leaves the construction a dig cue."""
        from sugar_lift_py_tests.floor import DictValue, ListValue, SetValue, TupleValue
        from sugar_lift_py_tests.outcome import ExitSet

        if operation.keyword_names or len(operation.arguments) > 1:
            return None
        if not operation.arguments:
            return ExitSet.completed(SetValue(()))
        source = operation.arguments[0]
        if isinstance(source, DictValue):
            return ExitSet.completed(SetValue(tuple(key for key, _ in source.entries)))
        if isinstance(source, SetValue):
            return ExitSet.completed(SetValue(tuple(source.elements)))
        if not isinstance(source, (ListValue, TupleValue)):
            return None
        kept = []
        for member in source.elements:
            refused = _refuse_unhashable(member, operation, "python.set.construct")
            if refused is not None:
                return refused
            if not _hash_decided(member):
                return None
            found = _position(member, kept)
            if found is None:
                return None
            if found < 0:
                kept.append(member)
        return ExitSet.completed(SetValue(tuple(kept)))

    def _construct_tuple(self, operation):
        """Exact ``tuple(iterable)`` over finite authenticated containers.

        Generator expressions that projected ``finite_elements`` and ordinary
        list/tuple/set floors become ``TupleValue`` here. Opaque iterables stay
        a dig cue (via ``_unhandled_construct``) rather than inventing
        cardinality or panicking the factory membrane.
        """
        from sugar_lift_py_tests.floor import (
            ComprehensionValue,
            DictValue,
            ListValue,
            SetValue,
            TupleValue,
        )
        from sugar_lift_py_tests.outcome import ExitSet

        if operation.keyword_names or len(operation.arguments) > 1:
            return None
        if not operation.arguments:
            return ExitSet.completed(TupleValue(()))
        source = operation.arguments[0]
        if isinstance(source, TupleValue):
            return ExitSet.completed(source)
        if isinstance(source, (ListValue, SetValue)):
            return ExitSet.completed(TupleValue(tuple(source.elements)))
        if isinstance(source, DictValue):
            return ExitSet.completed(
                TupleValue(tuple(key for key, _ in source.entries))
            )
        if (
            isinstance(source, ComprehensionValue)
            and source.finite_elements is not None
        ):
            return ExitSet.completed(TupleValue(tuple(source.finite_elements)))
        if isinstance(source, ComprehensionValue):
            from sugar_lift_py_tests.context_manager_resolution import (
                SourceFragmentCoordinateV1,
            )
            from sugar_lift_py_tests.floor.tuple_coordinate_value import (
                TupleCoordinateValue,
            )

            if type(operation.call_occurrence) is SourceFragmentCoordinateV1:
                return ExitSet.completed(
                    TupleCoordinateValue._from_builtin_construct(
                        source=source,
                        call_occurrence=operation.call_occurrence,
                        runtime=self.runtime_identity,
                    )
                )
        return None

    def _construct_dict(self, operation):
        """Construct ``dict`` from an authenticated mapping or pair iterable.

        CPython walks the pairs in order: an item that is not iterable raises
        ``TypeError``, one whose length is not 2 raises ``ValueError``, an
        unhashable key raises ``TypeError``; a repeated key keeps its first
        position and takes the last value."""
        from sugar_lift_py_tests.floor import (
            BytesValue,
            DictValue,
            ListValue,
            NoneValue,
            TermValue,
            TupleValue,
        )
        from sugar_lift_py_tests.outcome import ExitSet
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        if operation.keyword_names or len(operation.arguments) > 1:
            return None
        if not operation.arguments:
            return ExitSet.completed(DictValue(()))
        source = operation.arguments[0]
        if isinstance(source, DictValue):
            return ExitSet.completed(source)
        if not isinstance(source, (ListValue, TupleValue)):
            return None
        owner = "python.dict.construct"
        keys: list = []
        values: list = []
        for item in source.elements:
            if type(item) in (
                TermValue,
                NoneValue,
                TrueBoolLiteralSugar,
                FalseBoolLiteralSugar,
            ):
                return _ground_refusal("TypeError", operation, owner)
            if type(item) is BytesValue:
                return None
            if not isinstance(item, (ListValue, TupleValue)):
                return None
            if len(item.elements) != 2:
                return _ground_refusal("ValueError", operation, owner)
            key, value = item.elements
            refused = _refuse_unhashable(key, operation, owner)
            if refused is not None:
                return refused
            if not _hash_decided(key):
                return None
            found = _position(key, keys)
            if found is None:
                return None
            if found < 0:
                keys.append(key)
                values.append(value)
            else:
                values[found] = value
        return ExitSet.completed(DictValue(tuple(zip(keys, values))))

    def test_python_type(self, value, site):
        """Constructor builtins that are also types answer isinstance tests.

        ``tuple`` / ``set`` are both callables and type objects. Binding them as
        construct callables must not lose ``isinstance(x, tuple)`` — RaisesExc
        gates on that exact condition.
        """
        type_name = {
            "python.tuple.construct": "tuple",
            "python.set.construct": "set",
        }.get(self.operation)
        if type_name is None:
            return super().test_python_type(value, site)
        from sugar_lift_py_tests.ir import ctor, str_const

        return value.python_isinstance(
            type_name,
            ctor("python:type", [str_const(type_name)]),
            site,
        )

    def witness_for(self, operands, result) -> ClosedSemanticOperationWitness:
        return ClosedSemanticOperationWitness.mint(
            self.runtime_identity,
            self.operation,
            tuple(value.to_term(owner=self.operation) for value in operands),
            result.to_term(owner=self.operation),
        )


def _ground_refusal(name, operation, owner):
    from .ground_exit import ground_exceptional_exit

    return ground_exceptional_exit(
        exception_name=name, site=operation.site, owner=f"BuiltinSemanticCallable.{owner}"
    )


def _refuse_unhashable(member, operation, owner):
    """``TypeError`` when ``member`` decidedly cannot be hashed, else None."""
    from .membership import decided_unhashable

    if decided_unhashable(member):
        return _ground_refusal("TypeError", operation, owner)
    return None


def _hash_decided(member) -> bool:
    from .builtin_container_method import _hash_decided as decided

    return decided(member)


def _position(member, kept):
    """Index of the first kept member equal to ``member``, -1, or None."""
    from .builtin_container_method import _index_of

    return _index_of(tuple(kept), member)
