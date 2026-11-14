from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.sugar.sugar_base import (
    ConstructedTermSugar,
    require_constructed_term_sugar,
)


@dataclass(frozen=True)
class ReceiverFieldStoreStateSugar(ConstructedTermSugar):
    """An object after one field store: ``receiver`` with ``attr`` set to
    ``value``.  ``value`` is the store's key read (``place``): the value the
    store statement completed with, never the stored expression evaluated
    again.  A read of a whole object after its field stores is these folded
    over the object's own read (``ReceiverFieldStoreState``, a coordinate
    receiver after ``o.x = v``; ``ObjectPlaceStateV1``, an object a
    constructor call built, read through its assignment's key)."""

    receiver: ConstructedTermSugar
    value: ConstructedTermSugar
    attr: str
    site: object = field(compare=False)

    @classmethod
    def witnesses(cls):
        return ()

    def __post_init__(self):
        require_constructed_term_sugar(
            self.receiver, owner="ReceiverFieldStoreStateSugar.receiver"
        )
        require_constructed_term_sugar(
            self.value, owner="ReceiverFieldStoreStateSugar.value"
        )

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:receiver-field-store-state",
            (
                self.occurrence_term(owner=owner),
                self.receiver.to_term(owner=owner),
                str_const(self.attr),
                self.value.to_term(owner=owner),
            ),
            symbol_kind="coordinate",
        )

    def desugar(self, ctx=None):
        from sugar_lift_py_tests.floor import CallSiteValue
        from sugar_lift_py_tests.floor.object_value import ObjectValue
        from sugar_lift_py_tests.gap.panic import construction_panic_gap
        from sugar_lift_py_tests.outcome import ExitSet

        def update(receiver, value):
            if (
                isinstance(receiver, CallSiteValue)
                and receiver.body is not None
                and receiver.source_call_frame_cid is not None
            ):
                # An object read through its constructor call's key
                # (``ObjectPlaceStateV1``): the authenticated call's floor, as
                # an attribute read takes it (``AttributeSugar``).
                receiver = receiver.force_floor(
                    ctx,
                    owner="authenticated receiver field store",
                    project_callsite=False,
                )
            if not isinstance(receiver, ObjectValue):
                construction_panic_gap(
                    owner="ReceiverFieldStoreStateSugar",
                    blame=self.site,
                    observed=type(receiver).__name__,
                    requested="authenticated source receiver",
                    fix="retain field mutation as typed loud until its receiver floors",
                )
            return ExitSet.completed(receiver.with_field_store(self.attr, value))

        return self.receiver.desugar(ctx).and_then(
            lambda receiver: self.value.desugar(ctx).and_then(
                lambda value: update(receiver, value)
            )
        )
