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
        from sugar_lift_py_tests.floor import ObjectField

        from sugar_source_tree.panic import SugarNotWritten

        class_fields = []
        base_values = []
        # Every direct base in source order, authenticated or not (``None``
        # for one whose evaluation refused).  ``base_values`` is the class
        # model's roster; this is the testimony of what the roster omits, so
        # MRO selection never mistakes a later base for the first one.
        direct_bases = []
        body_faces = []
        for base in self.base_sugars:
            try:
                outcome = base.desugar(ctx)
            except SugarNotWritten as exc:
                # A from-import name such as ``typing.Generic`` is now an
                # ImportMemberValue. ``Generic[T]`` subscripts that member
                # with a type variable and refuses; the class model already
                # omits every floor that is not a known class. Do not abort
                # construction for that refuse, and do not invent a Generic
                # specialization.
                if getattr(exc, "owner", None) != "ImportMemberValue.subscript":
                    raise
                direct_bases.append(None)
                continue
            from sugar_lift_py_tests.floor import BuiltinDictClassValue, ClassValue

            if not isinstance(outcome, Complete):
                # A base that is a local class whose body may raise (a field
                # initializer calling C code): the base expression completes
                # on one face and halts on the other.  The halt is sequenced
                # before this class body exactly like a field's, never dropped.
                value = _sole_completed_value(outcome)
                if value is not _NO_SOLE_COMPLETION and isinstance(
                    value, ClassDefinitionValue
                ):
                    body_faces.append(outcome)
                    outcome = Complete(value)
            direct_bases.append(
                outcome.value if isinstance(outcome, Complete) else None
            )
            if isinstance(outcome, Complete) and isinstance(
                outcome.value, (ClassDefinitionValue, BuiltinDictClassValue)
            ):
                base_values.append(outcome.value)
            elif (
                isinstance(outcome, Complete)
                and type(outcome.value) is ClassValue
                and outcome.value.name == "type"
            ):
                # ``type`` is an exact Python builtin class binding. Retaining
                # it is what lets zero-argument super in a source metaclass
                # select type.__new__; no other generic ClassValue is admitted.
                base_values.append(outcome.value)
            # HEAD omitted unenrolled bases from this roster.  This increment
            # evaluates them only to discover the exact BuiltinDictClassValue;
            # every other Floor remains outside the class model and gains no
            # authority or behavior here.

        evaluated_groups = {}

        def append_field(item):
            if isinstance(item, ConstructedClassConditionalFieldsV1):
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
                selected = (
                    item.when_true
                    if isinstance(condition.value, TrueBoolLiteralSugar)
                    else item.when_false
                )
                for child in selected:
                    append_field(child)
                return
            outcome = (
                evaluated_groups.get(item.evaluation_group_cid)
                if item.evaluation_group_cid is not None
                else None
            )
            if outcome is None:
                outcome = item.value_sugar.desugar(ctx)
                if item.evaluation_group_cid is not None:
                    evaluated_groups[item.evaluation_group_cid] = outcome
            if not isinstance(outcome, Complete):
                value = _sole_completed_value(outcome)
                if value is _NO_SOLE_COMPLETION:
                    from sugar_source_tree.panic import SugarNotWritten

                    raise SugarNotWritten(
                        blame=self.site,
                        owner="ClassDefinitionSugar.desugar",
                        observed=f"class field {item.name} did not construct completely",
                        requested="one exact constructed class-field value",
                        fix="keep effectful or unresolved class initializers loud",
                    )
                # The initializer may raise (#7585): executing the class body
                # halts with it, and the class exists only on the one
                # completed face.  Faces are sequenced in source order.
                body_faces.append(outcome)
                class_fields.append(ObjectField(item.name, value))
                return
            class_fields.append(ObjectField(item.name, outcome.value))

        for item in self.fields:
            append_field(item)
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
        constructed = Complete(
            ClassDefinitionValue(
                self.class_name,
                self.class_definition_cid,
                self.methods,
                initializer,
                self.binding_target_occurrence,
                tuple(class_fields),
                self.docstring_cid,
                self.annotation_cids,
                self.decorator_cids,
                tuple(base_values),
                direct_bases=tuple(direct_bases),
            )
        )
        if not body_faces:
            return constructed
        outcome = Complete(None)
        for faces in body_faces:
            outcome = outcome.and_then(lambda _, faces=faces: faces)
        return outcome.and_then(lambda _: constructed)


_NO_SOLE_COMPLETION = object()


def _sole_completed_value(outcome):
    """The value of an outcome whose only non-halting face is one completion.

    A class-field initializer that may raise has that halt plus one completed
    value, so executing the class body is two-faced.  Several completions
    (distinct field values) or any other face stay refused.
    """
    from sugar_lift_py_tests.outcome.exit_set import Completed, ExitSet, Halted

    if not isinstance(outcome, ExitSet):
        return _NO_SOLE_COMPLETION
    completed = [face for face in outcome.exits if isinstance(face, Completed)]
    if len(completed) != 1 or any(
        not isinstance(face, (Completed, Halted)) for face in outcome.exits
    ):
        return _NO_SOLE_COMPLETION
    return completed[0].value
