from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_python_source.canonical import cid_of_json
from sugar_lift_py_tests.floor.class_definition_value import (
    ClassDefinitionValue,
    ConstructedClassFieldV1,
    ConstructedClassMethodV1,
)
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing


@dataclass(frozen=True)
class ClassDefinitionSugar(Sugar):
    class_name: str
    source_identity_cid: str
    definition_fragment_cid: str
    methods: tuple[ConstructedClassMethodV1, ...]
    fields: tuple[ConstructedClassFieldV1, ...]
    docstring_cid: str | None
    annotation_cids: tuple[str, ...]
    decorator_cids: tuple[str, ...]
    site: object = field(compare=False)

    @classmethod
    def witnesses(cls):
        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="ClassDefinitionValue",
            reason="class structure is source testimony, not a proposition",
        )

    @property
    def preimage(self):
        return {
            "kind": "python-class-definition",
            "schemaVersion": "1",
            "sourceIdentityCid": self.source_identity_cid,
            "definitionFragmentCid": self.definition_fragment_cid,
            "methods": [
                {
                    "name": method.name,
                    "definitionFragmentCid": method.definition_fragment_cid,
                    "sourceCallFrameCid": method.source_call_frame.frame_cid,
                }
                for method in self.methods
            ],
            "fields": [
                {
                    "name": item.name,
                    "definitionFragmentCid": item.definition_fragment_cid,
                }
                for item in self.fields
            ],
            "docstringCid": self.docstring_cid,
            "annotationCids": list(self.annotation_cids),
            "decoratorCids": list(self.decorator_cids),
        }

    @property
    def class_definition_cid(self) -> str:
        return cid_of_json(self.preimage)

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.floor import ObjectField

        class_fields = []
        for item in self.fields:
            outcome = item.value_sugar.desugar(ctx)
            if not isinstance(outcome, Complete):
                from sugar_source_tree.panic import SugarNotWritten

                raise SugarNotWritten(
                    owner="ClassDefinitionSugar.desugar",
                    observed=f"class field {item.name} did not construct completely",
                    requested="one exact constructed class-field value",
                    fix="keep effectful or unresolved class initializers loud",
                )
            class_fields.append(ObjectField(item.name, outcome.value))
        initializer = next(
            (method for method in self.methods if method.name == "__init__"), None
        )
        return Complete(
            ClassDefinitionValue(
                self.class_name,
                self.class_definition_cid,
                self.methods,
                initializer,
                tuple(class_fields),
                self.docstring_cid,
                self.annotation_cids,
                self.decorator_cids,
            )
        )
