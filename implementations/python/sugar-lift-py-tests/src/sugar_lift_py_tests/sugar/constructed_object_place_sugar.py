from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class ConstructedObjectPlaceSugar(Sugar):
    value: object = field(compare=False)
    testimony: object
    site: object = field(compare=False)

    @classmethod
    def witnesses(cls):
        from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing

        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="FloorValue",
            reason="projects one already-constructed value from authenticated testimony",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx
        from sugar_lift_py_tests.ir import _term_content_cid
        from sugar_source_tree.binding_provenance import BindingProvenanceGap

        observed = _term_content_cid(
            self.value.to_term(owner="ConstructedObjectPlaceSugar")
        )
        if observed != self.testimony.semantic_value_cid:
            raise BindingProvenanceGap("constructed object projection mismatch")
        return Complete(self.value)
