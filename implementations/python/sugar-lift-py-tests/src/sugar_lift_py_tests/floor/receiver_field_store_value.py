from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue


@dataclass(frozen=True)
class ReceiverFieldStoreValue(FloorValue):
    receiver: FloorValue
    attr: str
    value: FloorValue

    def guarded(self, formula):
        from sugar_lift_py_tests.outcome.exit_set import _is_true

        # A store stamped with truth is still unconditional. Folded
        # ``if isinstance(match, str):`` re-stamps the tail with
        # true_guard; wrapping that as a branch hid ``_fail_reason``
        # from the super().__init__ splice.
        if _is_true(formula):
            return self
        from .guarded_receiver_field_store_value import (
            GuardedReceiverFieldStoreValue,
        )

        return GuardedReceiverFieldStoreValue(
            self.receiver, self.attr, self.value, formula
        )

    def extend_scope(self, ctx):
        """Advance every binding that names this exact constructed receiver."""
        from .object_identity import as_the_alias_holds
        from .object_value import ObjectValue

        if not isinstance(self.receiver, ObjectValue):
            return ctx
        updated = self.receiver.with_field_store(self.attr, self.value)
        return advanced_bindings(
            ctx,
            self.receiver,
            lambda candidate: as_the_alias_holds(updated, candidate),
            owner="ReceiverFieldStoreValue",
        )

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:receiver-field-store",
            [
                self.receiver.to_term(owner=owner),
                str_const(self.attr),
                self.value.to_term(owner=owner),
            ],
        )


def advanced_bindings(ctx, receiver, after_for, *, owner: str):
    """``ctx`` with every binding that names ``receiver``'s exact constructed
    object rebound to ``after_for(candidate)``, the object after the one
    field store as that binding holds it: the one alias advance of a field
    store -- the plain store's (``ReceiverFieldStoreValue.extend_scope``) and
    a store that ran code's (``ReceiverFieldStoreSugar``).  ``ctx`` itself
    when no binding names it."""
    from sugar_lift_py_tests.sugar.call_site_sugar import bound_value_read

    from .object_value import ObjectValue

    # Root mint is Floor-owned when the reducer has no ambient context yet.
    if ctx is None:
        from sugar_lift_py_tests.context import ReduceContext

        ctx = ReduceContext.root(owner=owner)
    temporal = ctx.temporal
    identity = receiver.identity
    matched = False
    for binding in ctx.temporal.bindings:
        # Every binding is read as any read reads it: a module-final
        # key demands its module run, whether or not a read asked first.
        candidate = bound_value_read(binding.value)
        if (
            isinstance(candidate, ObjectValue)
            and type(candidate) is type(receiver)
            and candidate.identity == identity
        ):
            temporal = temporal.bind_value(
                binding.name,
                after_for(candidate),
                blame=binding.blame,
                kind=type(binding),
            )
            matched = True
    return ctx.with_temporal(temporal) if matched else ctx
