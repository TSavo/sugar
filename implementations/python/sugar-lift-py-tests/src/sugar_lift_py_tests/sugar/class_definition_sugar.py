from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_python_source.canonical import cid_of_json
from sugar_lift_py_tests.ir import _term_content_cid
from sugar_lift_py_tests.context_manager_resolution import SourceFragmentCoordinateV1
from sugar_lift_py_tests.floor.class_definition_value import (
    ClassNamespaceMemberV1,
    ClassDefinitionValue,
    ConstructedClassFieldV1,
    ConstructedClassMethodV1,
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


@dataclass(frozen=True)
class ClassNamespaceSugarMemberV1:
    kind: str
    name: str
    binding_target_occurrence: SourceFragmentCoordinateV1
    value: object = field(compare=False, repr=False)


@dataclass(frozen=True)
class ClassDefinitionSugar(Sugar):
    class_name: str
    source_identity_cid: str
    definition_fragment_cid: str
    methods: tuple[ConstructedClassMethodV1, ...]
    fields: tuple[ConstructedClassFieldV1 | ConstructedClassConditionalFieldsV1, ...]
    namespace_roster: tuple[ClassNamespaceSugarMemberV1, ...]
    docstring_cid: str | None
    annotation_cids: tuple[str, ...]
    decorator_cids: tuple[str, ...]
    binding_target_occurrence: SourceFragmentCoordinateV1
    base_sugars: tuple[Sugar, ...]
    base_fragment_cids: tuple[str, ...]
    has_explicit_metaclass: bool
    site: object = field(compare=False)
    decorator_sugars: tuple[Sugar, ...] = field(default=(), compare=False)
    decorator_occurrences: tuple[object, ...] = field(default=(), compare=False)

    def __post_init__(self):
        positions = tuple(
            (member.binding_target_occurrence.start_line, member.binding_target_occurrence.start_col)
            for member in self.namespace_roster
        )
        if positions != tuple(sorted(positions)):
            raise ValueError("class namespace roster is not in source order")
        if any(
            member.kind not in {"field", "method", "conditional"}
            or member.binding_target_occurrence.source_cid != self.source_identity_cid
            for member in self.namespace_roster
        ):
            raise ValueError("class namespace roster has foreign kind or occurrence")

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
                {
                    "name": method.name,
                    "definitionFragmentCid": method.definition_fragment_cid,
                    "sourceCallFrameCid": method.source_call_frame.frame_cid,
                    "descriptorKind": method.descriptor_kind,
                }
                for method in self.methods
            ],
            "fields": [encode_field(item) for item in self.fields],
            "namespaceRoster": [
                {
                    "kind": member.kind,
                    "name": member.name,
                    "bindingTargetOccurrence": member.binding_target_occurrence.wire(),
                }
                for member in self.namespace_roster
            ],
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

        class_fields = []
        class_field_occurrences = []
        evaluated_namespace_roster = []
        base_values = []
        unresolved_base = False
        for base in self.base_sugars:
            outcome = base.desugar(ctx)
            from sugar_lift_py_tests.floor import (
                BuiltinDictClassValue,
                BuiltinObjectClassValue,
                ClassValue,
            )

            if isinstance(outcome, Complete) and isinstance(
                outcome.value,
                (
                    ClassDefinitionValue,
                    BuiltinDictClassValue,
                    BuiltinObjectClassValue,
                ),
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
            else:
                unresolved_base = True

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
                from sugar_source_tree.panic import SugarNotWritten

                raise SugarNotWritten(
                    blame=self.site,
                    owner="ClassDefinitionSugar.desugar",
                    observed=f"class field {item.name} did not construct completely",
                    requested="one exact constructed class-field value",
                    fix="keep effectful or unresolved class initializers loud",
                )
            class_fields.append(ObjectField(item.name, outcome.value))
            class_field_occurrences.append(item.binding_target_occurrence)
            evaluated_namespace_roster.append(
                ClassNamespaceMemberV1(
                    "field",
                    item.name,
                    item.binding_target_occurrence,
                    outcome.value,
                )
            )

        for member in self.namespace_roster:
            if member.kind == "method":
                evaluated_namespace_roster.append(
                    ClassNamespaceMemberV1(
                        "method",
                        member.name,
                        member.binding_target_occurrence,
                        member.value,
                    )
                )
            else:
                append_field(member.value)
        initializer = next(
            (method for method in self.methods if method.name == "__init__"), None
        )
        return Complete(
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
                tuple(class_field_occurrences),
                tuple(evaluated_namespace_roster),
                (
                    not self.has_explicit_metaclass
                    and not unresolved_base
                    and all(
                        not isinstance(base, ClassDefinitionValue)
                        or base.ordinary_instancecheck
                        for base in base_values
                    )
                ),
            )
        )
