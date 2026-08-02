from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar


@dataclass(frozen=True)
class ConstructedObjectPlaceSugar(ConstructedTermSugar):
    """Authenticated object-place currency as nested-construction testimony.

    ObjectPlaceStateV1 projects a constructed object (with field-version
    identity) into expression slots. AttributeSugar.receiver and peer
    ConstructedTermSugar slots were truthful — this class was missing the
    base that admits it as nested-construction testimony (same judgment as
    ConstructedReceiverRefSugar / #7099 Spread-Complex-Ellipsis promotions).

    Promote, do not widen AttributeSugar.receiver: an object place IS a
    constructed term (identity + testimony of the object), not a distinct
    un-termed sugar that slots must special-case.
    """

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

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        # Nested-construction coordinate: occurrence + authenticated semantic
        # testimony cid + the constructed value's term. Value must already
        # admit to_term (it is the projected floor / constructed object).
        value_term = self.value.to_term(owner=owner)
        testimony_cid = getattr(self.testimony, "semantic_value_cid", None)
        if not isinstance(testimony_cid, str):
            raise TypeError(
                f"{owner}: ConstructedObjectPlaceSugar.testimony requires "
                f"semantic_value_cid str, got {type(self.testimony).__name__}"
            )
        return ctor(
            "python:constructed-object-place",
            (
                self.occurrence_term(owner=owner),
                str_const(testimony_cid),
                value_term,
            ),
            symbol_kind="coordinate",
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
