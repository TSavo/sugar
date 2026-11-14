from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

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

        cited = _cited_builtins().get(self.operation)
        if cited is not None:
            decided = self._ground_call(operation, *cited)
            if decided is not None:
                return decided
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
            return self.re_application(operation)
        if self.operation == "python.isinstance":
            return self._isinstance(operation)
        if self.operation == "python.len":
            return self._len(operation)
        if self.operation == "python.enumerate.construct":
            return self._enumerate(operation, ctx)
        if self.operation == "python.super.construct":
            if operation.arguments or operation.keyword_names:
                return super().callable_application_with(operation, ctx)
            return zero_argument_super(operation.site, ctx)
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

    def _ground_call(self, operation, name: str, language_callee):
        """This builtin over ground operands: the cited fold's answer, or None.

        When every operand is a ground value (``builtin_ground_call``) the
        call's one answerer is the pinned interpreter's own builtin
        (``cpython_cited_fold``): ``len('ab')`` is ``2``, ``tuple(5)`` the one
        ``TypeError`` halt, ``set([1, 2, 1])`` is ``{1, 2}``, ``enumerate``
        the iterator of its pairs.  When that fold decides nothing (a host
        ``MemoryError``) the call is the one unanswered call.  None when an
        operand is not ground: the floor below folds what its shape decides.
        """
        from sugar_lift_py_tests.source_call_resolution import (
            UnknownCalleeCallV1,
            builtin_ground_call,
            cpython_cited_fold,
        )

        args = operation.arguments
        keyword_names = tuple(operation.keyword_names or ())
        if not builtin_ground_call(language_callee, args, keyword_names):
            return None
        callsite = _builtin_callsite(operation, name, language_callee)
        unanswered = UnknownCalleeCallV1(name)
        folded = cpython_cited_fold(
            unanswered,
            args,
            keyword_names,
            site=operation.site,
            language_callee=language_callee,
            callsite=callsite,
        )
        if folded is not None:
            return folded
        return unanswered.faces(callsite, operation.site)

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
        shape ``builtin_call_total`` lists.  Ground operands never reach here
        (``_ground_call`` answers them).  Otherwise it is the one unanswered
        call (``builtin_dunder_call``, else ``UnknownCalleeCallV1``):
        two-faced, its completed face this coordinate (#7757: a halt is never
        dropped).
        """
        from sugar_lift_py_tests.outcome import ExitSet
        from sugar_lift_py_tests.source_call_resolution import (
            UnknownCalleeCallV1,
            builtin_call_total,
            builtin_dunder_call,
        )

        args = operation.arguments
        keyword_names = tuple(operation.keyword_names or ())
        callsite = _builtin_callsite(operation, name, language_callee)
        if builtin_call_total(language_callee, args, keyword_names):
            return ExitSet.completed(callsite)
        unanswered = builtin_dunder_call(language_callee, args, keyword_names)
        if unanswered is None:
            unanswered = UnknownCalleeCallV1(name)
        return unanswered.faces(callsite, operation.site)

    def _len(self, operation):
        """``len(container)`` over an operand that is not ground, whose floor
        knows its size by its shape (a list of symbolic members, a
        comprehension); a ground operand is the cited fold's (``_ground_call``)."""
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
        """Construct the exact finite iterator for an authenticated sequence
        that is not ground (a member known only by its type, a finite
        comprehension): its shape decides the pairs.  A ground sequence is
        the cited fold's (``_ground_call``)."""
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

    def re_application(self, operation, *, target_symbol=None):
        """``re.search``/``re.match``/``re.fullmatch`` applied, decided or not.

        ``re_cited_fold`` is the call's one answerer: ground operands are the
        pinned interpreter's own ``re`` (a truthy ``ReMatchValue``,
        ``NoneValue``, or a builtin raise's one halt); a ground ``str``
        pattern over a subject known only to be a ``str`` completes on the two
        faces of ``py.re_<name>(pattern, subject)``, owing nothing.  What it
        does not decide (a subject whose type is undecided, a keyword actual,
        a pattern that does not compile) is the one unanswered call: two-faced,
        owing one debt, its symbol ``target_symbol`` when the callee is
        import-bound (#7757).
        """
        from sugar_lift_py_tests.source_call_resolution import (
            UnknownCalleeCallV1,
            re_cited_fold,
        )

        name, language_callee = _re_functions()[self.operation]
        if not operation.keyword_names:
            decided = re_cited_fold(name, operation.arguments, operation.site)
            if decided is not None:
                return decided
        qualified = f"re.{name}"
        callsite = _builtin_callsite(
            operation, qualified, language_callee, target_symbol=target_symbol
        )
        return UnknownCalleeCallV1(qualified).faces(callsite, operation.site)

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
        does not decide leaves the construction a dig cue.  Reached only when
        the operand is not ground (a member known only by its type, a set):
        a ground operand is the cited fold's (``_ground_call``)."""
        from sugar_lift_py_tests.floor import DictValue, ListValue, SetValue, TupleValue
        from sugar_lift_py_tests.outcome import ExitSet

        from sugar_lift_py_tests.floor.object_identity import contents_stale, made_at

        if operation.keyword_names or len(operation.arguments) != 1:
            return None
        source = operation.arguments[0]
        if contents_stale(source):
            # Its members are not its contents now: not iterated here.
            return None
        # A new set made by this call, from current contents.
        allocation = made_at(operation.site)
        if isinstance(source, DictValue):
            return ExitSet.completed(
                SetValue(
                    tuple(key for key, _ in source.entries), allocation=allocation
                )
            )
        if isinstance(source, SetValue):
            return ExitSet.completed(
                SetValue(tuple(source.elements), allocation=allocation)
            )
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
        return ExitSet.completed(SetValue(tuple(kept), allocation=allocation))

    def _construct_tuple(self, operation):
        """Exact ``tuple(iterable)`` over finite authenticated containers.

        Generator expressions that projected ``finite_elements`` and ordinary
        list/tuple/set floors become ``TupleValue`` here. Opaque iterables stay
        a dig cue (via ``_unhandled_construct``) rather than inventing
        cardinality or panicking the factory membrane.  Reached only when the
        operand is not ground (a member known only by its type, a set, a
        comprehension): a ground operand is the cited fold's (``_ground_call``).
        """
        from sugar_lift_py_tests.floor import (
            ComprehensionValue,
            DictValue,
            ListValue,
            SetValue,
            TupleValue,
        )
        from sugar_lift_py_tests.floor.object_identity import contents_stale
        from sugar_lift_py_tests.outcome import ExitSet

        if operation.keyword_names or len(operation.arguments) != 1:
            return None
        source = operation.arguments[0]
        if contents_stale(source):
            # Its members are not its contents now: not iterated here.
            return None
        if isinstance(source, TupleValue):
            # CPython's ``tuple(t)`` hands back an exact tuple itself
            # (``PySequence_Tuple``): the same object, not a copy.
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
        position and takes the last value.  Reached only when the operand is
        not ground (a key or value known only by its type): a ground operand
        is the cited fold's (``_ground_call``).

        ``dict(d)`` over a dict is a new dict, never ``d`` itself: CPython's
        ``dict_new`` allocates and copies ``d``'s entries (shallow, the same
        key and value objects, in ``d``'s order).  ``e = dict(d); e['k'] = 1``
        leaves ``d`` as it was, and ``dict(d) is d`` is False."""
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

        from sugar_lift_py_tests.floor.object_identity import (
            contents_stale,
            made_at,
        )

        if operation.keyword_names or len(operation.arguments) != 1:
            return None
        source = operation.arguments[0]
        if contents_stale(source):
            # Its members are not its contents now: not iterated here.
            return None
        if isinstance(source, DictValue):
            # A new dict made by this call, holding ``source``'s entries
            # (current: a stale ``source`` returned above).
            return ExitSet.completed(
                DictValue(tuple(source.entries), allocation=made_at(operation.site))
            )
        if not isinstance(source, (ListValue, TupleValue)):
            return None
        owner = "python.dict.construct"
        keys: list = []
        values: list = []
        for item in source.elements:
            if contents_stale(item):
                return None
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
        # A new dict made by this call, from current contents.
        return ExitSet.completed(
            DictValue(tuple(zip(keys, values)), allocation=made_at(operation.site))
        )

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


_POSITIONAL_PARAM_KINDS = frozenset({"positional_only", "positional_or_keyword"})

# The first argument of a generator expression's code: ``.0``, the iterator
# of its outermost iterable -- a positional argument no source formal names.
_GENERATOR_ITERATOR_ARGUMENT = ".0"


def _super_frame_first_positional(site):
    """``(read, formal)`` for a zero-argument ``super()`` at ``site``: whether
    the frame it runs in is read, and that frame's first positional
    argument (None when it takes none).

    The frame is the innermost code object running the call
    (``SourceUnit.frame_holding``): a ``def``, a ``lambda`` -- a function of
    its own, whose code has its own arguments -- a generator expression, a
    class body, or the module.  A function or a lambda takes its declared
    positional formals; a generator expression takes exactly one, ``.0``
    (``_GENERATOR_ITERATOR_ARGUMENT``); a list, set or dict comprehension is
    no frame (inlined, PEP 709).  A site with no source unit is not read.
    """
    from sugar_source_tree.nodes import GeneratorExp

    unit = getattr(site, "unit", None)
    node = getattr(site, "node", None)
    if unit is None or node is None:
        return False, None
    frame = unit.frame_holding(node.line_col_span())
    if isinstance(frame, GeneratorExp):
        return True, _GENERATOR_ITERATOR_ARGUMENT
    params = tuple(getattr(frame, "params", None) or ())
    if not params or params[0].param_kind not in _POSITIONAL_PARAM_KINDS:
        return True, None
    return True, params[0]


_SUPER_OWNER = "BuiltinSemanticCallable.python.super"


def zero_argument_super(site, ctx):
    """``super()`` with no actual at ``site``, in CPython's own order
    (``super_init_without_args``, then ``supercheck``, Objects/typeobject.c):

    1. a frame whose code takes no positional argument raises
       ``RuntimeError`` (``zero_argument_super_has_no_arguments``);
    2. a frame with no ``__class__`` cell of its own raises ``RuntimeError:
       super(): __class__ cell not found`` -- decided by the frame's own
       symtable block (``zero_argument_super_class_cell``), never by a
       ``__class__`` some caller bound;
    3. a generator expression's first argument is its ``.0`` iterator,
       which is no instance of the class ``__class__`` holds: ``supercheck``
       raises ``TypeError``;
    4. otherwise ``super(__class__, obj)`` with ``obj`` the frame's first
       formal (``zero_argument_super_receiver``) and ``__class__`` the
       frame's cell, read as the class value the context binds for that
       class statement: ``BuiltinSuperValue.constructed``, which makes the
       instance check.

    Each decided failure is the call's halt.  A cell or receiver not read
    here refuses by name.
    """
    from sugar_lift_py_tests.floor.builtin_super_value import BuiltinSuperValue
    from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

    if zero_argument_super_has_no_arguments(site):
        return ground_exceptional_exit(
            exception_name="RuntimeError", site=site, owner=_SUPER_OWNER
        )
    decided, cell = zero_argument_super_class_cell(site)
    if decided and cell is None:
        return ground_exceptional_exit(
            exception_name="RuntimeError", site=site, owner=_SUPER_OWNER
        )
    if decided and zero_argument_super_in_generator_frame(site):
        return ground_exceptional_exit(
            exception_name="TypeError", site=site, owner=_SUPER_OWNER
        )
    temporal = getattr(ctx, "temporal", None)
    current_class = _class_cell_value(cell, temporal) if decided else None
    receiver = zero_argument_super_receiver(site, temporal)
    if current_class is None or receiver is None:
        from sugar_lift_py_tests.gap.panic import construction_panic_gap

        construction_panic_gap(
            owner=_SUPER_OWNER,
            blame=str(site),
            observed=(
                "the frame's __class__ cell is not read"
                if not decided
                else "the frame's __class__ cell holds no class value here"
                if current_class is None
                else "the frame's first formal is not bound"
            ),
            requested="authenticated zero-argument super context",
            fix="carry the defining class and bound first formal into the method body",
        )
    return BuiltinSuperValue.constructed(current_class, receiver, site)


def zero_argument_super_class_cell(site):
    """``(decided, cell)`` for a zero-argument ``super()`` at ``site``: whether
    the frame running it has a ``__class__`` cell of its own and the class
    statement it holds (``SourceUnit.frame_class_cell``, off the frame's own
    symtable block).  Not decided for a site with no source unit."""
    unit = getattr(site, "unit", None)
    node = getattr(site, "node", None)
    if unit is None or node is None:
        return False, None
    return unit.frame_class_cell(node.line_col_span())


def _class_cell_value(cell, temporal):
    """The class value the frame's ``__class__`` cell holds: the context's
    ``__class__`` binding when it is the class the cell's statement makes
    (matched by source occurrence).  A binding of any other class is a
    caller's, never this frame's cell: None."""
    from sugar_source_tree.occurrence import SourceOccurrenceIdentityV1

    if temporal is None or cell is None:
        return None
    bound = temporal.value_if_bound("__class__")
    statement = getattr(bound, "class_definition", None)
    if statement is None:
        return None
    if statement is cell or SourceOccurrenceIdentityV1.of(
        statement
    ) == SourceOccurrenceIdentityV1.of(cell):
        return bound
    return None


def zero_argument_super_in_generator_frame(site) -> bool:
    """Whether a zero-argument ``super()`` at ``site`` runs in a generator
    expression's own frame, whose first argument -- the object ``super()``
    binds -- is the generator's ``.0`` iterator, never a formal of the
    function around it: with a ``__class__`` cell, ``supercheck``'s
    ``TypeError`` (``zero_argument_super``)."""
    _read, formal = _super_frame_first_positional(site)
    return formal is _GENERATOR_ITERATOR_ARGUMENT


def zero_argument_super_has_no_arguments(site) -> bool:
    """Whether a zero-argument ``super()`` at ``site`` is CPython's
    ``RuntimeError: super(): no arguments``.

    ``super_init_without_args`` (Objects/typeobject.c) raises it first, for
    any frame whose code has ``co_argcount == 0``: a ``def`` or ``lambda``
    with no positional formal (``*args`` and keyword-only formals do not
    count), a class body, the module.  So ``lambda: super().m()`` inside a
    method raises it, though the method has a ``self``: the frame is the
    lambda's (``_super_frame_first_positional``).  A generator expression's
    code takes ``.0``, so it never raises this.
    """
    read, formal = _super_frame_first_positional(site)
    return read and formal is None


def zero_argument_super_receiver(site, temporal):
    """The receiver a zero-argument ``super()`` at ``site`` binds, or None.

    CPython's rule (``super_init_without_args``, Objects/typeobject.c): the
    first positional formal of the frame that runs the call, read as that
    frame binds it.  The frame is the innermost ``def`` or ``lambda`` whose
    body holds the call (``_super_frame_first_positional``): a lambda's code
    is its own frame, and the compiler gives it the ``__class__`` cell
    (``symtable`` marks ``__class__`` free in any function block that reads
    ``super``), so ``lambda x: super().m()`` inside a method binds ``x``, not
    the method's ``self``.  The formal is the one the source declares,
    whatever it is spelled: ``def m(this): super().m()`` reads ``this``, and
    a ``self`` some enclosing frame binds is never read in its place.  A
    frame with no positional formal is CPython's ``RuntimeError``
    (``zero_argument_super_has_no_arguments``) and has no receiver; neither
    does a site with no source unit, nor a formal the frame has not bound
    (the builtin floor's own binding of the same spelling is not the
    frame's formal): None.  Nor does a generator expression's frame here:
    its first argument is the ``.0`` iterator, which no temporal binds
    (``zero_argument_super_in_generator_frame``); the enclosing function's
    formal is never read in its place.
    """
    from sugar_lift_py_tests.temporal.builtin_name_bindings import (
        is_builtin_floor_binding,
    )

    if temporal is None:
        return None
    _read, formal = _super_frame_first_positional(site)
    if formal is None or formal is _GENERATOR_ITERATOR_ARGUMENT:
        return None
    binding = temporal.latest(formal.name)
    if binding is None or is_builtin_floor_binding(binding):
        return None
    return binding.value


@lru_cache(maxsize=1)
def _cited_builtins():
    """``operation -> (name, LanguageCallee)``: the builtin semantic callables
    that are dunder-invoking builtins, whose call over ground operands the
    cited fold answers (``BuiltinSemanticCallable._ground_call``)."""
    from sugar_source_tree.nodes import LanguageCallee

    return {
        "python.len": ("len", LanguageCallee.BUILTIN_LEN),
        "python.enumerate.construct": ("enumerate", LanguageCallee.BUILTIN_ENUMERATE),
        "python.set.construct": ("set", LanguageCallee.BUILTIN_SET),
        "python.tuple.construct": ("tuple", LanguageCallee.BUILTIN_TUPLE),
        "python.dict.construct": ("dict", LanguageCallee.BUILTIN_DICT),
    }


@lru_cache(maxsize=1)
def _re_functions():
    """``operation -> (re function name, LanguageCallee)``: the ``re``
    functions whose call ``re_cited_fold`` answers
    (``BuiltinSemanticCallable.re_application``)."""
    from sugar_source_tree.nodes import LanguageCallee

    return {
        "python.re.search": ("search", LanguageCallee.RE_SEARCH),
        "python.re.match": ("match", LanguageCallee.RE_MATCH),
        "python.re.fullmatch": ("fullmatch", LanguageCallee.RE_FULLMATCH),
    }


def _builtin_callsite(operation, name, language_callee, *, target_symbol=None):
    """The bodiless call coordinate of this builtin's application: it carries
    the ``LanguageCallee`` the binding is, so a reader asks the binding,
    never the spelling ``name`` (#7757), and the one import table's target
    symbol when the callee is import-bound (``target_symbol``)."""
    from sugar_lift_py_tests.call_symbol import call_symbol
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.ir import ctor

    args = operation.arguments
    owner = str(operation.site)
    return CallSiteValue(
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
        authenticated_target_symbol=target_symbol,
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
