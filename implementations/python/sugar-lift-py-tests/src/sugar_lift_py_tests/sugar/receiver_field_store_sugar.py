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
      value read off a binding -- is decided by the one class lookup on its
      type (``ObjectValue.field_store_route``: the store is
      ``type(receiver).__setattr__``):

      - a class that takes ``object``'s ``__setattr__`` and binds no data
        descriptor for the name takes the plain store (``setattr``; a
        property with no setter this lookup selects refuses with
        ``AttributeError``); the statement records the store
        (``ReceiverFieldStoreValue``), which advances every binding of the
        object (``extend_scope``) and is what a call carries to its caller
        (``caller_visible_stores``).  The field is then known on the object
        even where it arrived (``ObjectValue.stored_fields``); the rest of
        it stays as its currency says.
      - a class whose lookup selects a source ``__setattr__``, or a source
        descriptor's ``__set__`` for the name, runs that function: the store
        is that call (``ObjectValue.field_store_call``), applied like any
        call, its halts the store's and its value recorded as a call in
        statement position is (``record_statement_value``: what it did to
        what this frame sees rides it, ``caller_visible_stores``).
      - a class whose lookup does not decide (an unread base, a builtin
        base with a ``__setattr__`` of its own, a member not decided) is the
        one unanswered call: two faces, owed.

      A store that ran code leaves the receiver as that call states it
      (``ObjectValue.after_field_store_call``: where it states nothing, the
      same instance with its contents not current, so no field of it is
      decided), bound under ``after``, the key the receiver's post-state
      reads it through after the statement.
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
    # The key a store that ran code binds the receiver after it under
    # (``nodes._receiver_field_store``); None for a statement never
    # substituted, whose receiver no post-state reads.
    after: str | None = field(default=None, compare=False)
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
        if not isinstance(receiver, ObjectValue):
            return project_setattr(receiver, self.attr, value, self.site, ctx)
        if not receiver.field_store_runs_code(self.attr):
            return receiver.setattr(self.attr, value, self.site, ctx).and_then(
                lambda _after: ExitSet.completed(
                    ReceiverFieldStoreValue(receiver, self.attr, value)
                )
            )
        # The store is a call: the one the class lookup selected, or the
        # unanswered one.
        outcome = receiver.field_store_call(self.attr, value, self.site, ctx)
        if not isinstance(outcome, ExitSet):
            # A deferred native operation of the body: the caller's to
            # discharge, as for any call.
            return outcome
        return outcome.and_then(lambda result: self._ran(receiver, result, ctx))

    def _ran(self, receiver, result, ctx) -> ExitSet:
        """The record of a store that ran code and completed with ``result``
        (the call's value): the call, recorded as a call in statement
        position is (``record_statement_value``: the stores it carries to
        this frame are laid in the record), carrying the receiver after it
        (``ObjectValue.after_field_store_call``) as a write under ``after``,
        where the receiver's post-state reads it
        (``ReceiverFieldStoreStateSugar``).  Every binding that names the
        object holds it as the call left it from here
        (``advanced_bindings``, the one alias advance of a field store):
        never the object as it was before the store."""
        from dataclasses import replace

        from sugar_lift_py_tests.context import ReduceContext
        from sugar_lift_py_tests.floor.named_expression_value import (
            NamedExpressionValue,
            carry_walrus_binds,
            peel_walrus_binds,
        )
        from sugar_lift_py_tests.floor.receiver_field_store_value import (
            advanced_bindings,
        )
        from sugar_lift_py_tests.sugar.expr_statement_sugar import (
            record_statement_value,
        )
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            statement_record,
        )

        if ctx is None:
            ctx = ReduceContext.root(owner="ReceiverFieldStoreSugar")
        after = receiver.after_field_store_call(result, self.site)
        binds, call = peel_walrus_binds(result)
        if self.after is not None:
            binds = (
                *binds,
                NamedExpressionValue(
                    self.attr, after(receiver), evaluation=self.after
                ),
            )

        def advanced(block):
            # The record the statement leaves, in the context the call's
            # record leaves (``statement_record``), with the object's
            # bindings advanced.
            record = statement_record(block, ctx)
            return ExitSet.completed(
                replace(
                    record,
                    context=advanced_bindings(
                        record.context,
                        receiver,
                        after,
                        owner="ReceiverFieldStoreSugar",
                    ),
                )
            )

        return record_statement_value(carry_walrus_binds(binds, call), ctx).and_then(
            advanced
        )


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
