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
    over the object's own read (``ReceiverFieldStoreState``, the one field
    store's post-state, whatever the receiver was given: an object a
    constructor call built, ``ObjectPlaceStateV1``, is read through its
    assignment's key underneath).

    The store itself ran at its statement (``ReceiverFieldStoreSugar``); this
    read of the object after it runs nothing, and the receiver's value
    decides what it reads: an instance of a source class (``ObjectValue``)
    with the field stored -- known on it whether it was made here or arrived
    (``ObjectValue.stored_fields``), the rest of it as its currency says; a
    value of another decided runtime type as its own floor's store leaves it;
    and a formal with no actual or an undecided value the object it is, whose
    fields no read here decides."""

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
        from sugar_lift_py_tests.floor.object_value import ObjectValue
        from sugar_lift_py_tests.outcome import ExitSet
        from sugar_lift_py_tests.sugar.receiver_field_store_sugar import (
            floored_receiver,
        )

        def update(receiver, value):
            receiver = floored_receiver(receiver, ctx)
            if isinstance(receiver, ObjectValue):
                return ExitSet.completed(receiver.with_field_store(self.attr, value))
            if (
                getattr(receiver, "formal_coordinate", None) is None
                and receiver.runtime_type_is_decided()
            ):
                # A decided runtime type answers its own store: the object
                # after it is its floor's, as the store statement had it (a
                # floor that does not answer stays loud).
                return receiver.setattr(self.attr, value, self.site, ctx)
            # A formal with no actual, or an undecided value: the object it
            # is, every field read undecided.
            return ExitSet.completed(receiver)

        return self.receiver.desugar(ctx).and_then(
            lambda receiver: self.value.desugar(ctx).and_then(
                lambda value: update(receiver, value)
            )
        )
