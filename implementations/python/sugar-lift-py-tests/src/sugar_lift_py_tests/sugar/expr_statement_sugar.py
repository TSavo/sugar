"""An expression in statement position -- `<expr>` on its own line.

The census's #2 family, and mostly docstrings. A bare expression STATES no
fact: its value reduces (the recursion -- a docstring to its string, a method
call to its coordinate) and then contributes nothing to the record. What DOES
ride is an effect: a halted arm propagates itself through and_then, so
`raise`-bearing or unresolvable expressions stay red testimony, never dropped.
"""

from __future__ import annotations

from typing import ClassVar

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import inert_statement_return_witness


@dataclass(frozen=True)
class ExprStatementSugar(Sugar):
    halts_at_statement_head: ClassVar[bool] = True

    value: Sugar
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        return inert_statement_return_witness(
            name="expr_statement_inert",
            owner_sugar="ExprStatementSugar",
            statement='"""a docstring"""',
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        # Reduce the value (effects propagate via and_then). A completed value
        # in statement position STATES nothing -- but it is not erased: it rides
        # as a record entry, contributing only what its own floor defaults give
        # (a docstring: nothing; a call coordinate: its callEdge cue, and its
        # visibility to the effect router -- dropping it made `with raises(E):
        # do_thing()` claim a FALSE absence, since the router could no longer
        # see that a halt might hide behind the unresolved call).
        #
        # One statement value is more than a coordinate: an authenticated
        # `warnings.warn(msg, Category)` occurrence. It rides as the warning
        # testimony the completed-face boundary consumes. The projection lives
        # HERE rather than in CallSiteSugar because statement position is what
        # makes it an occurrence -- a warn call read as an expression operand
        # would be a value, and this record entry is not one. An occurrence
        # that does not authenticate keeps its ordinary call coordinate and the
        # boundary names it unresolved; it is never read as "no warning".
        #
        # A receiver field store's post-state (``o.x = v``,
        # ``ReceiverFieldStoreState``) reads its stored value through the
        # store statement's key (``KeyedStoreSugar``), so a later read of
        # ``o`` never evaluates ``v`` again: it needs no record of its own.
        return self.value.desugar(ctx).and_then(
            lambda value: self._record_statement_value(value, ctx)
        )

    def _record_statement_value(self, value, ctx):
        from sugar_lift_py_tests.floor.block_value import BlockValue
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
        from sugar_lift_py_tests.floor.named_expression_value import (
            carry_walrus_binds,
            peel_walrus_binds,
        )
        from sugar_lift_py_tests.sugar.warning_observation_producer import (
            project_warning_observation,
        )

        # A walrus the expression evaluated (``(x := 5)``, ``f((x := 5))``)
        # binds the rest of the block: the record carries its binds
        # (``BlockValue.extend_scope``), and the value it presents is what
        # this statement reads (a call stays a call).
        binds, value = peel_walrus_binds(value)
        recorded = carry_walrus_binds(binds, project_warning_observation(value) or value)
        # ``super().__init__(...)`` is a constructor call in statement
        # position: it exists for its field stores, not as a value. Leaving
        # the CallSiteValue unreduced dropped AbstractRaises.__init__ stores
        # (``self._fail_reason: str | None = None``). Reducing the body
        # alone is not enough: those stores update a nested temporal and
        # ``__init__`` returns None, so the constructing receiver never
        # sees them. Splice unguarded receiver-field stores from the
        # completed body into this statement's record so the outer
        # constructor block can apply them. A store whose guard is
        # truth — including a nested empty-and — is unconditional: a
        # folded ``isinstance(match, str)`` still stamps the tail with
        # true_guard, and that is not a branch. Real branch stores stay
        # in the nested ExitSet rather than being flattened onto one
        # receiver. Keep the call coordinate so effect routing still
        # sees the call.
        #
        # A bodyful free-function call (``runtime_dispatch_receiver``
        # absent) is the same kind of statement: it exists for its
        # effect. Leaving ``fail("DID NOT RAISE")`` as an unreduced
        # CallSiteValue leaked those calls into a completed ``__exit__``
        # face even after ``_Fail.__call__`` was seated. Method calls
        # other than ``__init__`` keep their receiver and stay nested.
        if (
            isinstance(value, CallSiteValue)
            and value.body is not None
            and (
                value.target_name == "__init__"
                or value.target_name.endswith(".__init__")
                or value.runtime_dispatch_receiver is None
            )
        ):
            from sugar_lift_py_tests.floor.guarded_receiver_field_store_value import (
                GuardedReceiverFieldStoreValue,
            )
            from sugar_lift_py_tests.floor.receiver_field_store_value import (
                ReceiverFieldStoreValue,
            )

            def _store_guard_is_unconditional(guard):
                from sugar_lift_py_tests.outcome.exit_set import _is_true

                if _is_true(guard):
                    return True
                if getattr(guard, "kind", None) == "and":
                    operands = getattr(guard, "operands", ())
                    return all(
                        _store_guard_is_unconditional(operand)
                        for operand in operands
                    )
                return False

            def _unconditional_field_store(statement):
                if isinstance(statement, GuardedReceiverFieldStoreValue):
                    if _store_guard_is_unconditional(statement.guard):
                        return ReceiverFieldStoreValue(
                            statement.receiver,
                            statement.attr,
                            statement.value,
                        )
                    return None
                if isinstance(statement, ReceiverFieldStoreValue):
                    return statement
                return None

            def pack(result):
                extras = ()
                if isinstance(result, BlockValue):
                    extras = tuple(
                        store
                        for store in (
                            _unconditional_field_store(statement)
                            for statement in result.statements
                        )
                        if store is not None
                    )
                return ExitSet.completed(
                    BlockValue((recorded, *extras), can_fall_through=True)
                )

            # The Call producer already reduced the body once (its halts left
            # at the Call); consume that completion, never replay it.
            retained = value.retained_source_completion_outcome()
            if retained is not None:
                return retained.and_then(pack)

            # No completion kept: apply the call the one way, through
            # ``producer_outcome`` (#7757 entry 6) -- native operations
            # discharge against the bound actuals and the body's raises are
            # the Call's own.  Each completed face is the Call carrying the
            # body completion it retained; the statement splices that body.
            def body_completion(result):
                if isinstance(result, CallSiteValue) and result.term is value.term:
                    completed = result.retained_source_completion_outcome()
                    if completed is not None:
                        return completed.completed_value()
                return result

            return value.producer_outcome(ctx).and_then(
                lambda result: pack(body_completion(result))
            )
        return ExitSet.completed(BlockValue((recorded,), can_fall_through=True))
