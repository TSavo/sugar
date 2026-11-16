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
    call built, ``OpaqueObjectStateV1``, is read through its
    assignment's key underneath).

    The store itself ran at its statement (``ReceiverFieldStoreSugar``); this
    read of the object after it runs nothing, and the receiver's value
    decides what it reads, as it decided the store: an instance of a source
    class (``ObjectValue``) whose class takes the plain store
    (``ObjectValue.field_store_route``) with the field stored -- known on it
    whether it was made here or arrived (``ObjectValue.stored_fields``), the
    rest of it as its currency says -- and whose class refuses the store (a
    property with no setter the lookup selects) the ``AttributeError`` its
    store raises (``ObjectValue.setattr``); an instance whose store ran code (a
    ``__setattr__``, a descriptor's ``__set__``, an undecided class lookup)
    as that call left it, read through the key the statement bound it under
    (``after``) -- unknown where the statement bound none, never the object
    with the field assumed stored; a value of another decided runtime type
    as its own floor's store leaves it; and a formal with no actual or an
    undecided value the object it is, whose fields no read here decides."""

    receiver: ConstructedTermSugar
    value: ConstructedTermSugar
    attr: str
    site: object = field(compare=False)
    # The key the store statement binds the receiver under after a store
    # that ran code (``nodes._receiver_field_store``).
    after: str | None = field(default=None, compare=False)

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
                if receiver.field_store_runs_code(self.attr):
                    return self._left(ctx)
                # The store the one class lookup decides
                # (``ObjectValue.field_store_route``), answered by the
                # receiver's own store: the plain store completes with the
                # field stored, a property with no setter the lookup selects
                # halts with ``AttributeError`` -- the same answer the store
                # statement gives (``ReceiverFieldStoreSugar``).
                return receiver.setattr(self.attr, value, self.site, ctx)
            if (
                getattr(receiver, "formal_coordinate", None) is None
                and receiver.runtime_type_is_decided()
            ):
                # A decided runtime type answers its own store: the object
                # after it is its floor's, as the store statement had it (a
                # floor that does not answer stays loud).
                return receiver.setattr(self.attr, value, self.site, ctx)
            if getattr(receiver, "constructed_by_edge", False):
                # A same-file class call's result names the instance as its
                # construction left it, whose fields the class's contract
                # states (#7757 step 7): after a store it is not that state,
                # so it is the object after code this read does not see.
                from sugar_lift_py_tests.sugar.builtin_container_call_sugar import (
                    _unknown_after,
                )

                return ExitSet.completed(_unknown_after(self.site, f".{self.attr}"))
            # A formal with no actual, or an undecided value: the object it
            # is, every field read undecided.
            return ExitSet.completed(receiver)

        return self.receiver.desugar(ctx).and_then(
            lambda receiver: self.value.desugar(ctx).and_then(
                lambda value: update(receiver, value)
            )
        )

    def _left(self, ctx):
        """The receiver after a store that ran code: the value its statement
        bound under ``after`` (``ReceiverFieldStoreSugar._ran``), read as any
        key is where this read stands (``evaluation_read_here``).  Where no
        such key is bound here -- the statement's own evaluation of the
        state before its store ran (``KeyedStoreSugar.writes``), a statement
        never substituted, a read outside the frame that ran the store -- an
        unknown minted at the store: the object after code this read does
        not see.  Either is one completed arm, the key's read owing what it
        owes (``TemporalContext.key_read``)."""
        from sugar_lift_py_tests.outcome import ExitSet
        from sugar_lift_py_tests.sugar.builtin_container_call_sugar import (
            _unknown_after,
        )

        temporal = getattr(ctx, "temporal", None) if ctx is not None else None
        if self.after is not None and temporal is not None:
            from sugar_lift_py_tests.sugar.evaluation_ref_sugar import (
                evaluation_read_here,
            )

            left = temporal.key_read(evaluation_read_here(temporal, self.after))
            if left is not None:
                return left
        return ExitSet.completed(_unknown_after(self.site, f".{self.attr}"))
