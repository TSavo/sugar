from __future__ import annotations

from dataclasses import dataclass, field, replace

from sugar_lift_python_source.canonical import cid_of_json
from sugar_lift_py_tests.ir import _term_content_cid
from sugar_lift_py_tests.context_manager_resolution import SourceFragmentCoordinateV1
from sugar_lift_py_tests.floor.class_definition_value import (
    ClassDefinitionValue,
    ConstructedClassFieldV1,
    ConstructedClassMethodV1,
    DeferredClassMethodV1,
)
from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing


def _written_initializer(value):
    """The ``__init__`` method a class statement's own body wrote (``value``:
    its sugar or its class value): the last one, Python's live class
    binding."""
    return next(
        (method for method in reversed(value.methods) if method.name == "__init__"),
        None,
    )


@dataclass(frozen=True)
class ClassDefinitionSugar(Sugar):
    class_name: str
    source_identity_cid: str
    definition_fragment_cid: str
    methods: tuple[ConstructedClassMethodV1, ...]
    # One row per Name a statement of the body binds, in source order, an
    # ``if``'s arms included: the name, and the key the statement's sugar
    # binds its value under (``nodes.ClassDef._class_body_block``).  The
    # rows name the namespace; the body's block (``body``) evaluates it.
    fields: tuple[ConstructedClassFieldV1, ...]
    docstring_cid: str | None
    annotation_cids: tuple[str, ...]
    decorator_cids: tuple[str, ...]
    binding_target_occurrence: SourceFragmentCoordinateV1
    base_sugars: tuple[Sugar, ...]
    base_fragment_cids: tuple[str, ...]
    site: object = field(compare=False)
    decorator_sugars: tuple[Sugar, ...] = field(default=(), compare=False)
    decorator_occurrences: tuple[object, ...] = field(default=(), compare=False)
    # Per base, the sugar of the type arguments of a local ``Base[T]`` the
    # base unwraps to ``Base`` (``nodes.ClassDef._sugar_source_class_base``),
    # else None.  Python evaluates ``T`` right after reading ``Base``; its
    # value is not the class model's, every face of it is the statement's.
    base_type_arguments: tuple = field(default=(), compare=False)
    # The value of each class keyword (``metaclass=ABCMeta``), in source
    # order: Python evaluates them after the bases and before the body,
    # every face of each the statement's.
    keyword_sugars: tuple[Sugar, ...] = field(default=(), compare=False)
    # The class statement itself: its constructor frame is the one ``Cls(x)``
    # applies, whether the class is called by name or as a value.
    class_definition: object = field(default=None, compare=False)
    # The class body's statements' own sugars, in source order: the block
    # the class statement runs through the one block reducer, as a function
    # body or a module body runs (``_class_body``).  An ``if`` among them is
    # ``IfSugar``; a method's ``def`` statement is its defaults' evaluation.
    body: tuple = field(default=(), compare=False)
    # The indexes in ``fields`` of the rows that stand in an arm of an
    # ``if`` of the body: bound only on a face where that arm ran.
    branch_fields: frozenset = field(default=frozenset(), compare=False)
    # The branch slot of each ``if`` of the body.
    branch_slots: tuple = field(default=(), compare=False)
    # The key of each default of each method ``def`` statement
    # (``nodes._default_evaluation_key``), in source order.
    default_keys: tuple = field(default=(), compare=False)
    # The fragment CID of each ``def`` standing in an ``if`` or a ``with`` of
    # the body: its statement is built there, but no method roster (``methods``)
    # carries it, so the namespace is refused by name (``_namespace``).
    unrostered_definitions: tuple = field(default=(), compare=False)
    # True on the class statement's run (``statement_run``): each completed
    # face is the class carrying what its body's callees stored
    # (``CallerStoreValue``), for the statement to lay in its record.  False
    # on every read of the class value, which applies nothing.
    carries_body_stores: bool = field(default=False, compare=False)

    @classmethod
    def witnesses(cls):
        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="ClassDefinitionValue",
            reason="class structure is source testimony, not a proposition",
        )

    @property
    def preimage(self):
        def encode_field(item):
            return {
                "name": item.name,
                "definitionFragmentCid": item.definition_fragment_cid,
                "bindingTargetOccurrence": item.binding_target_occurrence.wire(),
                "evaluationGroupCid": item.evaluation_group_cid,
            }

        return {
            "kind": "python-class-definition",
            "schemaVersion": "1",
            "sourceIdentityCid": self.source_identity_cid,
            "definitionFragmentCid": self.definition_fragment_cid,
            "bindingTargetOccurrence": self.binding_target_occurrence.wire(),
            "methods": [
                (
                    {
                        # A deferred method body is not constructed at class
                        # definition: its source definition is its identity.
                        "name": method.name,
                        "definitionFragmentCid": method.definition_fragment_cid,
                        "deferredBody": True,
                        "descriptorKind": method.descriptor_kind,
                    }
                    if type(method) is DeferredClassMethodV1
                    else {
                        "name": method.name,
                        "definitionFragmentCid": method.definition_fragment_cid,
                        "sourceCallFrameCid": method.source_call_frame.frame_cid,
                        "descriptorKind": method.descriptor_kind,
                    }
                )
                for method in self.methods
            ],
            "fields": [encode_field(item) for item in self.fields],
            "docstringCid": self.docstring_cid,
            "annotationCids": list(self.annotation_cids),
            "decoratorCids": list(self.decorator_cids),
            "baseDefinitionCids": [
                (
                    base.class_definition_cid
                    if hasattr(base, "class_definition_cid")
                    else _term_content_cid(
                        base.to_term(owner="ClassDefinitionSugar.base")
                    )
                )
                for base in self.base_sugars
            ],
            "baseFragmentCids": list(self.base_fragment_cids),
        }

    @property
    def class_definition_cid(self) -> str:
        return cid_of_json(self.preimage)

    def desugar(self, ctx: object = None) -> ExitSet:
        # A class statement runs once: Python binds the class it builds, and
        # every ``Cls(...)`` reads that one class.  The statement is reduced
        # where it runs (the block that holds it, an enclosing class body's
        # field), and its name is bound to the class under its evaluation
        # key there; every read of the name -- a class call, a base, a
        # decorator, an ``__init__``'s own universe -- reads that key
        # (``DecoratorApplicationSugar``) and never reduces the statement
        # again (#7757 item 21).  A module-level statement's outcome is kept
        # with its sugar (``_ran``).  A statement nested in a function runs
        # at each call of that function, against that call's bindings.
        #
        # A halt of a base or of the class body leaves the statement before
        # any class exists: what the body bound is the class namespace, gone
        # with it, and nothing of the enclosing block was bound by the
        # statement. So the run records it where it halted, in the context
        # the statement runs in (``halt_record``), onto which the block
        # composition splices what ran before the ``class`` statement.
        #
        # The body runs once, at the statement: what its callees stored is
        # the statement's, laid in its record (``as_statement``), never the
        # class value's.  Every read of the class -- ``C`` alone, a call of
        # it, a decorator's argument -- presents the class beneath those
        # stores and applies none of them.
        from sugar_lift_py_tests.floor.named_expression_value import (
            peel_walrus_binds,
        )
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            halt_record,
            halts_recorded,
        )

        ran = halts_recorded(self._ran(ctx), halt_record(ctx))
        if self.carries_body_stores:
            return ran
        return ran.and_then(
            lambda carried: ExitSet.completed(peel_walrus_binds(carried)[1])
        )

    def _ran(self, ctx) -> ExitSet:
        """The statement's run: on each completed face, the class carrying
        its body's callee stores.  Only a module statement's run is kept: its
        one occurrence runs once, and the sugar it was read from keeps it
        (``statement_run`` shares it).  Every other class statement runs at
        each of its runs -- each item of a loop around it, each call of the
        function it stands in -- and no run is answered from another's: no
        evaluation is answered from a record of an earlier one."""
        if not self._is_module_statement():
            return self._reduce_statement(ctx)
        origin = self.__dict__.get("_run_of", self)
        reduced = origin.__dict__.get("_statement_outcome")
        if reduced is None:
            reduced = self._reduce_statement(ctx)
            object.__setattr__(origin, "_statement_outcome", reduced)
        return reduced

    def statement_run(self) -> "ClassDefinitionSugar":
        """The class statement's run: this sugar, each completed face of it
        the class carrying what its body's callees stored on objects the
        statement's frame sees (``carry_caller_stores``), as a call's value
        carries what its callee stored.  What runs the statement lays them
        where it lays a value's callee stores: a block (``as_statement``,
        ``record_statement_value``), an enclosing class body's field
        (``evaluate_assignment_values``), a decorated statement's assignment
        of its decorators' result (``DecoratorApplicationSugar.runs_statement``:
        the body's stores, then the decorators').  A shallow copy (stamps kept, as
        ``nodes._as_evaluation_of`` keeps them) that shares this sugar's one
        run."""
        if self.carries_body_stores:
            return self
        run = self.__dict__.get("_statement_run")
        if run is None:
            import copy

            run = copy.copy(self)
            object.__setattr__(run, "carries_body_stores", True)
            object.__setattr__(run, "_run_of", self.__dict__.get("_run_of", self))
            object.__setattr__(self, "_statement_run", run)
        return run

    def as_statement(self) -> Sugar:
        """The class statement where a block runs it: its run
        (``statement_run``) in statement position, which lays the body's
        callee stores in the statement's record and publishes them to the
        block (``ExprStatementSugar``, ``record_statement_value``) -- once,
        here, and at no read of the class."""
        statement = self.__dict__.get("_as_statement")
        if statement is None:
            from sugar_lift_py_tests.sugar.expr_statement_sugar import (
                ExprStatementSugar,
            )

            statement = ExprStatementSugar(value=self.statement_run(), site=self.site)
            object.__setattr__(self, "_as_statement", statement)
        return statement

    def _is_module_statement(self) -> bool:
        statement = self.class_definition
        if statement is None:
            return False
        module = statement.unit._require_typed_module(
            "ClassDefinitionSugar._is_module_statement", blame=statement.fragment
        )
        return any(item is statement for item in module.body)

    def _reduce_statement(self, ctx) -> ExitSet:
        # Python evaluates the base expressions, in order, before the class
        # body runs; if one raises, the statement raises and no class exists.
        # So the bases are an ordinary operand fold (#7755): ``and_then`` runs
        # the rest of the statement once under every completed face of a base
        # and carries every halt of it unchanged.  A base that never completes
        # leaves the statement with no completion at all; a base with several
        # completions builds the class once per completion, each with the
        # base it was built over.  A base that cannot be built refuses by
        # name: nothing here catches its refusal.
        body = []

        def class_body():
            # The body runs once, after all bases, whichever base face this is.
            if not body:
                body.append(self._class_body(ctx))
            return body[0]

        return self._fold_bases(self.base_sugars, (), ctx, class_body)

    def _fold_bases(self, remaining, evaluated, ctx, class_body) -> ExitSet:
        if not remaining:
            return self._fold_keywords(
                self.keyword_sugars, evaluated, ctx, class_body
            )
        head, *rest = remaining
        index = len(evaluated)
        arguments = (
            self.base_type_arguments[index]
            if index < len(self.base_type_arguments)
            else None
        )

        def then(value):
            return self._fold_bases(tuple(rest), (*evaluated, value), ctx, class_body)

        def read(value):
            # ``Base[T]`` unwrapped to ``Base``: ``T`` is evaluated after the
            # read, every face of it the statement's; the base is ``Base``.
            if arguments is None:
                return then(value)
            return arguments.desugar(ctx).and_then(lambda _arguments: then(value))

        return head.desugar(ctx).and_then(read)

    def _fold_keywords(self, remaining, evaluated_bases, ctx, class_body) -> ExitSet:
        # Each class keyword's value, in order, after the bases and before
        # the body: every face of each the statement's.  The class model
        # reads none of them (a metaclass is not modelled here).
        if not remaining:
            return self._construct(evaluated_bases, class_body)
        head, *rest = remaining
        return head.desugar(ctx).and_then(
            lambda _value: self._fold_keywords(
                tuple(rest), evaluated_bases, ctx, class_body
            )
        )

    def _construct(self, evaluated_bases, class_body) -> ExitSet:
        from sugar_lift_py_tests.floor import (
            BuiltinDictClassValue,
            BuiltinExceptionClassValue,
        )
        from sugar_lift_py_tests.temporal.builtin_name_bindings import (
            builtin_type_class,
        )

        base_values = []
        for value in evaluated_bases:
            if isinstance(
                value,
                (ClassDefinitionValue, BuiltinDictClassValue, BuiltinExceptionClassValue),
            ):
                # A builtin exception base is retained by the object the
                # builtin namespace binds (a source rebinding of its name
                # evaluates to another value): zero-argument
                # ``super().__init__(...)`` in a source exception class
                # reaches its ``__init__`` through it.
                base_values.append(value)
            elif value is builtin_type_class():
                # The builtin ``type`` class, by the object the builtin
                # namespace binds (never the spelling: a source ``class
                # type`` seeds an equal-looking ``ClassValue`` named
                # ``type``). Retaining it is what lets zero-argument super in
                # a source metaclass select type.__new__; no other generic
                # ClassValue is admitted.
                base_values.append(value)
            # Every other evaluated base (an opaque cited value, a symbolic
            # subscript) remains outside the class model and gains no
            # authority or behavior here; its faces were already carried by
            # the fold.
        def construct_class(body):
            from sugar_lift_py_tests.sugar.function_universe_sugar import (
                _ReducedBlock,
            )

            if not isinstance(body, _ReducedBlock) or not body.can_fall_through:
                # A completed body has one form: the record its block left
                # (``_class_body``), run to its end.  Any other completed
                # value is one whose rest does not run: the body did not run
                # to its end, so no class is built from it (#7799).
                from sugar_source_tree.panic import SugarNotWritten

                raise SugarNotWritten(
                    blame=self.site,
                    owner="ClassDefinitionSugar.desugar",
                    observed=(
                        f"class body completed with a {type(body).__name__}"
                        + (
                            " that does not fall through"
                            if isinstance(body, _ReducedBlock)
                            else ""
                        )
                        + ", which is not the body's record"
                    ),
                    requested="the record the class body's block left at its end",
                    fix="keep a class body that did not run to its end loud",
                )
            fields, method_defaults = self._namespace(body)
            value = ClassDefinitionValue(
                self.class_name,
                self.class_definition_cid,
                self.methods,
                None,
                self.binding_target_occurrence,
                fields,
                self.docstring_cid,
                self.annotation_cids,
                self.decorator_cids,
                tuple(base_values),
                class_definition=self.class_definition,
                method_defaults=method_defaults,
            )
            # The ``__init__`` a call of the class runs is the one the one
            # class-namespace lookup selects (``initializer_class``: this
            # class's own or an inherited one), the last ``def`` its class
            # body wrote -- Python's live class binding (overload stubs
            # written as ``def __init__(...): ...`` precede the
            # implementation).  None when the lookup does not decide a
            # source ``def``.
            owner = value.initializer_class()
            if owner is not None:
                value = replace(value, initializer=_written_initializer(owner))
            # What the body's callees stored ran at this statement: the run
            # carries it on the class it built (``statement_run``); the class
            # itself holds none of it.
            from sugar_lift_py_tests.floor.named_expression_value import (
                carry_caller_stores,
            )

            return ExitSet.completed(carry_caller_stores(body.entries, value))

        # The class exists only on a face the whole body completed under;
        # every halt of the body is the statement's halt, unchanged.
        return class_body().and_then(construct_class)

    def _class_body(self, ctx):
        """The body's run: the record its block leaves on each completed
        face, every halt of it kept.

        A class body is a block.  Its statements (``body``) run through the
        one block reducer (``reduce_block_to_exitset``), as a function body
        or a module body runs: each statement's own sugar evaluates it, in
        source order, a halt of one is the body's halt and no later
        statement runs under it, and an ``if`` is ``IfSugar`` -- its test
        taken by the one truth rule, the arm it selects reduced as the suite
        it is.  Nothing here decides a statement.
        """
        from sugar_lift_py_tests.outcome.exit_set import Completed
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            reduce_block_to_exitset,
        )

        outcome = reduce_block_to_exitset(self.body, ctx)
        if (
            isinstance(outcome, ExitSet)
            and sum(isinstance(face, Completed) for face in outcome.exits) > 1
        ):
            # A body with several completed faces (a field whose right-hand
            # side has several completed values) would build one class per
            # face.  That stays refused, as it always was (no such class has
            # been traced through a reader of the class value).  The block
            # does not say which statement it was, so the refusal names the
            # body's fields.
            from sugar_source_tree.panic import SugarNotWritten

            names = ", ".join(dict.fromkeys(item.name for item in self.fields))
            raise SugarNotWritten(
                blame=self.site,
                owner="ClassDefinitionSugar.desugar",
                observed=f"class field {names} did not construct completely",
                requested="one exact constructed class-field value",
                fix="keep effectful or unresolved class initializers loud",
            )
        return outcome

    def _namespace(self, record) -> tuple:
        """``(fields, method defaults)``: the class's namespace, read off
        the state the body's block left (``record``, its completed record).

        Each row of ``fields`` names a Name one statement of the body binds
        and the key that statement's sugar bound its value under; the
        namespace holds the value the state binds under that key, in source
        order, a later binding of a name after an earlier one (the class
        value reads the last).  A row in an arm of an ``if``
        (``branch_fields``) is bound exactly on a face where that arm ran:
        unbound, its statement did not run and the namespace holds nothing
        of it.  A row of the body itself whose key the state does not hold
        is refused by name, never dropped.  Each method default is the value
        the state binds under its key (``default_keys``); one the state does
        not hold is not carried, and a call that omits it is refused by name
        (``DefaultValueSugar``).

        An ``if`` the one truth rule did not decide on this face reduced
        both arms into one record, each under its branch guard
        (``IfSugar``): the record carries that ``if``'s branch-result
        authentication.  A name such an arm binds is bound under a guard the
        namespace's rows do not carry, so the namespace is not read from
        that state: refused by name, as an undecided class conditional
        always was.
        """
        from sugar_lift_py_tests.floor import ObjectField
        from sugar_lift_py_tests.floor.branch_result_coordinate import (
            BranchResultAuthentication,
        )
        from sugar_lift_py_tests.sugar.evaluation_ref_sugar import (
            evaluation_read_here,
        )
        from sugar_source_tree.panic import SugarNotWritten

        # An authentication held under an enclosing arm's guard (a nested
        # ``if``) is read as its enclosing ``if``'s, as before it kept its
        # guards (``BranchResultAuthentication.guards``).
        if any(
            isinstance(entry, BranchResultAuthentication)
            and not entry.guards
            and entry.slot.slot_id in self.branch_slots
            for entry in record.entries
        ):
            raise SugarNotWritten(
                blame=self.site,
                owner="ClassDefinitionSugar.desugar",
                observed="class conditional guard is not a ground bool literal",
                requested=(
                    "a class-body if whose test the truth rule decides on the "
                    "face the class is built on"
                ),
                fix=(
                    "read a name bound under an undecided branch as the "
                    "guarded binding it is, or keep the class loud"
                ),
            )
        if self.unrostered_definitions:
            # A ``def`` in an arm binds a method on the faces where its arm
            # ran; the class's methods are its roster (``methods``), which
            # carries none of them.  Building the class without it would drop
            # the method, so the namespace is refused, by name.
            raise SugarNotWritten(
                blame=self.site,
                owner="ClassDefinitionSugar.desugar",
                observed=(
                    f"class {self.class_name} defines "
                    f"{len(self.unrostered_definitions)} method(s) under an if "
                    "or a with of its body, which no method roster carries"
                ),
                requested=(
                    "a method roster that carries a def its body binds in a "
                    "compound statement"
                ),
                fix=(
                    "read an arm's def as the guarded method it is, or keep "
                    "the class loud"
                ),
            )
        temporal = getattr(record.context, "temporal", None)

        def bound(key):
            if temporal is None or key is None:
                return None
            return temporal.value_if_bound(evaluation_read_here(temporal, key))

        fields = []
        for index, row in enumerate(self.fields):
            value = bound(row.evaluation_key)
            if value is None:
                if index in self.branch_fields:
                    # The arm holding this statement did not run on this face.
                    continue
                raise SugarNotWritten(
                    blame=self.site,
                    owner="ClassDefinitionSugar.desugar",
                    observed=(
                        f"class field {row.name} is not bound in the state "
                        "its body's block left"
                    ),
                    requested=(
                        "the value the field's statement bound under its "
                        "evaluation key"
                    ),
                    fix="bind every class-body assignment under its key",
                )
            fields.append(ObjectField(row.name, value))
        defaults = tuple(
            (key, value)
            for key, value in ((key, bound(key)) for key in self.default_keys)
            if value is not None
        )
        return tuple(fields), defaults
