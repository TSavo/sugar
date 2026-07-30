from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_python_source.canonical import cid_of_json
from sugar_lift_py_tests.context_manager_resolution import SourceFragmentCoordinateV1
from sugar_lift_py_tests.floor.class_definition_value import (
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
                {
                    "name": method.name,
                    "definitionFragmentCid": method.definition_fragment_cid,
                    "sourceCallFrameCid": method.source_call_frame.frame_cid,
                    "descriptorKind": method.descriptor_kind,
                }
                for method in self.methods
            ],
            "fields": [encode_field(item) for item in self.fields],
            "docstringCid": self.docstring_cid,
            "annotationCids": list(self.annotation_cids),
            "decoratorCids": list(self.decorator_cids),
            "baseDefinitionCids": [
                base.class_definition_cid for base in self.base_sugars
            ],
            "baseFragmentCids": list(self.base_fragment_cids),
        }

    @property
    def class_definition_cid(self) -> str:
        return cid_of_json(self.preimage)

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.floor import ObjectField

        class_fields = []
        base_values = []
        for base in self.base_sugars:
            outcome = base.desugar(ctx)
            if not isinstance(outcome, Complete) or not isinstance(
                outcome.value, ClassDefinitionValue
            ):
                from sugar_source_tree.panic import SugarNotWritten

                raise SugarNotWritten(
                    blame=self.site,
                    owner="ClassDefinitionSugar.desugar",
                    observed="class base did not construct to ClassDefinitionValue",
                    requested="one authenticated source-visible base definition",
                    fix="keep dynamic or opaque inheritance loud",
                )
            base_values.append(outcome.value)

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

        for item in self.fields:
            append_field(item)
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
            )
        )
