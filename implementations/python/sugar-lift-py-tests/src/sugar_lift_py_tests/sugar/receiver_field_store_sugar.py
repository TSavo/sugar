from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar

from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class ReceiverFieldStoreSugar(Sugar):
    """``receiver.attr = value``: the one field store, whatever the
    receiver is.  Python evaluates ``value`` before the target, then the
    receiver, each once; the receiver's value decides the store here, at
    reduce, as the container-mutation door's receiver decides its call
    (``PathContainerCallSugar._apply``):

    - an instance of a source class (``ObjectValue``), made in this frame or
      arrived -- a formal's actual, a class call's coordinate receiver, a
      value read off a binding -- takes its own store (``setattr``: a
      property refuses with ``AttributeError``, an undecided class member
      refuses by name); the statement records the store
      (``ReceiverFieldStoreValue``), which advances every binding of the
      object (``extend_scope``) and is what a call carries to its caller
      (``caller_visible_stores``).  The field is then known on the object
      even where it arrived (``ObjectValue.stored_fields``); the rest of it
      stays as its currency says.
    - any other value takes the ordinary store
      (``store_effect_sugar.project_setattr``): a formal with no
      actual is the undischarged ``setattr_named`` demand, a decided runtime
      type its floor's store, an undecided one the store's two faces.

    ``value`` is the read of what the statement bound under its key
    (``KeyedStoreSugar``) when the statement was substituted, or the
    right-hand side itself when it never was.  The receiver's post-state,
    which every later read of the object reads, is
    ``ReceiverFieldStoreStateSugar``."""

    receiver: Sugar
    value: Sugar
    attr: str
    site: object = field(compare=False)
    # Nothing binds before a halt of the value, the receiver or the store:
    # its pre-halt record is the block's prefix.
    halts_at_statement_head: ClassVar[bool] = True

    @classmethod
    def witnesses(cls):
        from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing

        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="ReceiverFieldStoreValue",
            reason="the store is read through the receiver's post-state",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        # Python evaluates the right-hand side before the target.
        return self.value.desugar(ctx).and_then(
            lambda value: self.receiver.desugar(ctx).and_then(
                lambda receiver: self._store(receiver, value, ctx)
            )
        )

    def _store(self, receiver, value, ctx) -> ExitSet:
        from sugar_lift_py_tests.floor.object_value import ObjectValue
        from sugar_lift_py_tests.floor.receiver_field_store_value import (
            ReceiverFieldStoreValue,
        )
        from sugar_lift_py_tests.sugar.store_effect_sugar import project_setattr

        receiver = floored_receiver(receiver, ctx)
        if isinstance(receiver, ObjectValue):
            return receiver.setattr(self.attr, value, self.site, ctx).and_then(
                lambda _after: ExitSet.completed(
                    ReceiverFieldStoreValue(receiver, self.attr, value)
                )
            )
        return project_setattr(receiver, self.attr, value, self.site, ctx)


def floored_receiver(receiver, ctx):
    """``receiver`` as a field store or its post-state reads it: an object
    read through its authenticated constructor call's key is that call's
    floor, as an attribute read takes it (``AttributeSugar``); any other
    value is itself."""
    from sugar_lift_py_tests.floor import CallSiteValue

    if (
        isinstance(receiver, CallSiteValue)
        and receiver.body is not None
        and receiver.source_call_frame_cid is not None
    ):
        return receiver.force_floor(
            ctx,
            owner="authenticated receiver field store",
            project_callsite=False,
        )
    return receiver
