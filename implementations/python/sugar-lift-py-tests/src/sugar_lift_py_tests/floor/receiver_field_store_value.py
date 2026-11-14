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
        from sugar_lift_py_tests.sugar.call_site_sugar import bound_value_read

        from .object_identity import as_the_alias_holds
        from .object_value import ObjectValue

        if not isinstance(self.receiver, ObjectValue):
            return ctx
        # Root mint is Floor-owned when the reducer has no ambient context yet.
        if ctx is None:
            from sugar_lift_py_tests.context import ReduceContext

            ctx = ReduceContext.root(owner="ReceiverFieldStoreValue")
        updated = self.receiver.with_field_store(self.attr, self.value)
        temporal = ctx.temporal
        identity = self.receiver.identity
        matched = False
        for binding in ctx.temporal.bindings:
            # Every binding is read as any read reads it: a module-final
            # key demands its module run, whether or not a read asked first.
            candidate = bound_value_read(binding.value)
            if (
                isinstance(candidate, ObjectValue)
                and type(candidate) is type(self.receiver)
                and candidate.identity == identity
            ):
                temporal = temporal.bind_value(
                    binding.name,
                    as_the_alias_holds(updated, candidate),
                    blame=binding.blame,
                )
                matched = True
        return ctx.with_temporal(temporal) if matched else ctx

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
