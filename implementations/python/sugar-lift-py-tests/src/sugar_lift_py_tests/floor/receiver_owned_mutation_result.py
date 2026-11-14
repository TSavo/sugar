from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue


@dataclass(frozen=True)
class ReceiverOwnedMutationResult(FloorValue):
    """One immutable receiver transition plus the operation's Python result."""

    receiver_before: FloorValue
    receiver_after: FloorValue
    result: FloorValue

    def contribution(self):
        return (self,)

    def as_expression_statement(self):
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.completed(self)

    def answer(self, ctx=None):
        del ctx
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.completed(self.result)

    def project_operation_receiver(self, ctx, *, owner):
        del ctx, owner
        return self.result

    def extend_scope(self, ctx):
        """Advance every alias carrying this exact receiver identity."""
        if ctx is None:
            from sugar_lift_py_tests.context import ReduceContext

            ctx = ReduceContext.root(owner="ReceiverOwnedMutationResult")
        identity = getattr(self.receiver_before, "identity", None)
        if not isinstance(identity, str) or not identity:
            return ctx
        from sugar_lift_py_tests.sugar.call_site_sugar import bound_value_read

        from .object_identity import as_the_alias_holds

        temporal = ctx.temporal
        matched = False
        for binding in ctx.temporal.bindings:
            # Every binding is read as any read reads it: a module-final
            # key demands its module run, whether or not a read asked first.
            candidate = bound_value_read(binding.value)
            if (
                type(candidate) is type(self.receiver_before)
                and getattr(candidate, "identity", None) == identity
            ):
                temporal = temporal.bind_value(
                    binding.name,
                    as_the_alias_holds(self.receiver_after, candidate),
                    blame=binding.blame,
                )
                matched = True
        return ctx.with_temporal(temporal) if matched else ctx

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor

        return ctor(
            "python:receiver-owned-mutation-result",
            (
                self.receiver_before.to_term(owner=owner),
                self.receiver_after.to_term(owner=owner),
                self.result.to_term(owner=owner),
            ),
        )
