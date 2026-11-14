from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_python_source.canonical import cid_of_json
from sugar_lift_py_tests.ir import _term_content_cid
from sugar_lift_py_tests.context_manager_resolution import SourceFragmentCoordinateV1
from sugar_lift_py_tests.floor.class_definition_value import (
    ClassDefinitionValue,
    ConstructedClassFieldV1,
    ConstructedClassMethodV1,
    DeferredClassMethodV1,
)
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing


@dataclass(frozen=True)
class ConstructedClassConditionalFieldsV1:
    condition_fragment_cid: str
    condition_sugar: Sugar = field(compare=False)
    when_true: tuple[object, ...] = ()
    when_false: tuple[object, ...] = ()


def _inherited_source_initializer(bases):
    """The first authenticated source ``__init__`` on a local base class.

    Unauthenticated or builtin bases are not a source initializer.
    """
    for base in bases:
        if not isinstance(base, ClassDefinitionValue):
            return None
        own = next(
            (
                method
                for method in reversed(base.methods)
                if method.name == "__init__"
            ),
            None,
        )
        if own is not None:
            return own
        found = _inherited_source_initializer(base.base_classes)
        if found is not None:
            return found
    return None


@dataclass(frozen=True)
class ClassDefinitionSugar(Sugar):
    class_name: str
    source_identity_cid: str
    definition_fragment_cid: str
    methods: tuple[ConstructedClassMethodV1, ...]
    fields: tuple[ConstructedClassFieldV1 | ConstructedClassConditionalFieldsV1, ...]
    docstring_cid: str | None
    annotation_cids: tuple[str, ...]
    decorator_cids: tuple[str, ...]
    binding_target_occurrence: SourceFragmentCoordinateV1
    base_sugars: tuple[Sugar, ...]
    base_fragment_cids: tuple[str, ...]
    site: object = field(compare=False)
    decorator_sugars: tuple[Sugar, ...] = field(default=(), compare=False)
    decorator_occurrences: tuple[object, ...] = field(default=(), compare=False)
    # The class statement itself: its constructor frame is the one ``Cls(x)``
    # applies, whether the class is called by name or as a value.
    class_definition: object = field(default=None, compare=False)

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
            if isinstance(item, ConstructedClassFieldV1):
                return {
                    "name": item.name,
                    "definitionFragmentCid": item.definition_fragment_cid,
                    "bindingTargetOccurrence": item.binding_target_occurrence.wire(),
                    "evaluationGroupCid": item.evaluation_group_cid,
                }
            return {
                "kind": "conditional",
                "conditionFragmentCid": item.condition_fragment_cid,
                "whenTrue": [encode_field(child) for child in item.when_true],
                "whenFalse": [encode_field(child) for child in item.when_false],
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

    def desugar(self, ctx: object = None) -> Outcome:
        # A class statement runs once: Python binds the class it builds, and
        # every ``Cls(...)`` reads that one class.  So a module-level statement
        # is reduced once and its outcome kept with its sugar; every class call
        # (``ClassConstructorBodySugar``) and every other read of the statement
        # answers with that one outcome, never a second reduction (#7794).  A
        # statement nested in a function runs at each call of that function,
        # against that call's bindings, so it is reduced at each read.
        if not self._is_module_statement():
            return self._reduce_statement(ctx)
        reduced = self.__dict__.get("_statement_outcome")
        if reduced is None:
            reduced = self._reduce_statement(ctx)
            object.__setattr__(self, "_statement_outcome", reduced)
        return reduced

    def _is_module_statement(self) -> bool:
        statement = self.class_definition
        if statement is None:
            return False
        module = getattr(getattr(statement, "unit", None), "typed_module", None)
        return module is not None and any(
            item is statement for item in getattr(module, "body", ())
        )

    def _reduce_statement(self, ctx) -> Outcome:
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

    def _fold_bases(self, remaining, evaluated, ctx, class_body) -> Outcome:
        if not remaining:
            return self._construct(evaluated, class_body)
        head, *rest = remaining
        return head.desugar(ctx).and_then(
            lambda value: self._fold_bases(
                tuple(rest), (*evaluated, value), ctx, class_body
            )
        )

    def _construct(self, evaluated_bases, class_body) -> Outcome:
        from sugar_lift_py_tests.floor import BuiltinDictClassValue, ClassValue

        base_values = []
        for value in evaluated_bases:
            if isinstance(value, (ClassDefinitionValue, BuiltinDictClassValue)):
                base_values.append(value)
            elif type(value) is ClassValue and value.name == "type":
                # ``type`` is an exact Python builtin class binding. Retaining
                # it is what lets zero-argument super in a source metaclass
                # select type.__new__; no other generic ClassValue is admitted.
                base_values.append(value)
            # Every other evaluated base (an opaque cited value, a symbolic
            # subscript) remains outside the class model and gains no
            # authority or behavior here; its faces were already carried by
            # the fold.
        # The last same-name method is Python's live class binding. Overload
        # stubs written as ``def __init__(...): ...`` precede the implementation
        # (RaisesExc); the first ``__init__`` would construct through an
        # ellipsis body and drop every field store.
        initializer = next(
            (
                method
                for method in reversed(self.methods)
                if method.name == "__init__"
            ),
            None,
        )
        if initializer is None:
            initializer = _inherited_source_initializer(tuple(base_values))

        def construct_class(body_value):
            return Complete(
                ClassDefinitionValue(
                    self.class_name,
                    self.class_definition_cid,
                    self.methods,
                    initializer,
                    self.binding_target_occurrence,
                    body_value,
                    self.docstring_cid,
                    self.annotation_cids,
                    self.decorator_cids,
                    tuple(base_values),
                    class_definition=self.class_definition,
                )
            )

        # The class exists only on a face the whole body completed under;
        # every halt of the body is the statement's halt, unchanged.
        return class_body().and_then(construct_class)

    def _class_body(self, ctx):
        """The body's outcome: the class's fields on each completed face.

        A class field is an assignment.  Its right-hand side is evaluated by
        the routine every other assignment uses, in source order: a halt of a
        right-hand side is the body's halt and no later field runs under it.
        """
        from sugar_lift_py_tests.floor import ObjectField
        from sugar_lift_py_tests.sugar.assigned_value import (
            evaluate_assignment_values,
        )

        selected = []

        def select(item):
            if not isinstance(item, ConstructedClassConditionalFieldsV1):
                selected.append(item)
                return
            condition = item.condition_sugar.desugar(ctx)
            from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
                FalseBoolLiteralSugar,
            )
            from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
                TrueBoolLiteralSugar,
            )

            if not isinstance(condition, Complete) or not isinstance(
                condition.value, (TrueBoolLiteralSugar, FalseBoolLiteralSugar)
            ):
                from sugar_source_tree.panic import SugarNotWritten

                raise SugarNotWritten(
                    blame=self.site,
                    owner="ClassDefinitionSugar.desugar",
                    observed="class conditional guard is not a ground bool literal",
                    requested=(
                        "one constructed TrueBoolLiteralSugar or "
                        "FalseBoolLiteralSugar"
                    ),
                    fix="keep symbolic or effectful class-body control loud",
                )
            for child in (
                item.when_true
                if isinstance(condition.value, TrueBoolLiteralSugar)
                else item.when_false
            ):
                select(child)

        for item in self.fields:
            select(item)
        # ``a = b = e`` is one statement: its right-hand side is one value.
        values = []
        value_index = []
        groups = {}
        for item in selected:
            index = groups.get(item.evaluation_group_cid)
            if item.evaluation_group_cid is None or index is None:
                index = len(values)
                values.append(item.value_sugar)
                if item.evaluation_group_cid is not None:
                    groups[item.evaluation_group_cid] = index
            value_index.append(index)

        def bind_fields(active, completed):
            del active
            return Complete(
                tuple(
                    ObjectField(item.name, completed[index])
                    for item, index in zip(selected, value_index)
                )
            )

        outcome = evaluate_assignment_values(tuple(values), ctx, tail=bind_fields)
        from sugar_lift_py_tests.outcome.exit_set import Completed, ExitSet

        if (
            isinstance(outcome, ExitSet)
            and sum(isinstance(face, Completed) for face in outcome.exits) > 1
        ):
            # A field whose right-hand side has several completed values would
            # build one class per value.  That stays refused, as it always was
            # (no such class has been traced through a reader of the class
            # value).  The routine does not say which right-hand side it was,
            # so the refusal names the body's fields.
            from sugar_source_tree.panic import SugarNotWritten

            names = ", ".join(dict.fromkeys(item.name for item in selected))
            raise SugarNotWritten(
                blame=self.site,
                owner="ClassDefinitionSugar.desugar",
                observed=f"class field {names} did not construct completely",
                requested="one exact constructed class-field value",
                fix="keep effectful or unresolved class initializers loud",
            )
        return outcome
