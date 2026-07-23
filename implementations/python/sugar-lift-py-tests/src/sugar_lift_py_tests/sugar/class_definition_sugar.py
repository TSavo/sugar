from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_python_source.canonical import cid_of_json
from sugar_lift_py_tests.floor.class_definition_value import (
    ClassDefinitionValue,
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
        }

    @property
    def class_definition_cid(self) -> str:
        return cid_of_json(self.preimage)

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx
        initializer = next(
            (method for method in self.methods if method.name == "__init__"), None
        )
        return Complete(
            ClassDefinitionValue(
                self.class_name,
                self.class_definition_cid,
                self.methods,
                initializer,
            )
        )
