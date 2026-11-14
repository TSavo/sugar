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
            lambda value: record_statement_value(value, ctx)
        )


def record_statement_value(value, ctx):
    """The record a completed value in statement position makes: a
    ``BlockValue`` of the value and what it carries to its caller.  The one
    door's statement records its ordinary call's value here too
    (``ContainerMutationStatementSugar.records_value``): ``r.m(x)`` in
    statement position is one call, whichever door it takes."""
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.floor.named_expression_value import (
        caller_stores_of,
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
    # ``super().__init__(...)`` is a constructor call in statement
    # position: it exists for its field stores, not as a value. Leaving
    # the CallSiteValue unreduced dropped AbstractRaises.__init__ stores
    # (``self._fail_reason: str | None = None``). Reducing the body
    # alone is not enough: those stores update a nested temporal and
    # ``__init__`` returns None, so the constructing receiver never
    # sees them. The stores that reach the caller ride the call's
    # completed value (``CallerStoreValue``, the one projection at the
    # call, ``caller_visible_stores``, that a halt leaving the call takes
    # too); this statement lays them in its record so the outer
    # constructor block can apply them. Keep the call coordinate so
    # effect routing still sees the call.
    binds, stores = caller_stores_of(binds)
    recorded = carry_walrus_binds(binds, project_warning_observation(value) or value)
    # A bodyful free-function call (``runtime_dispatch_receiver``
    # absent) is the same kind of statement: it exists for its
    # effect. Leaving ``fail("DID NOT RAISE")`` as an unreduced
    # CallSiteValue leaked those calls into a completed ``__exit__``
    # face even after ``_Fail.__call__`` was seated. Method calls
    # other than ``__init__`` keep their receiver and stay nested
    # (``carries_its_stores_to_the_caller``).
    from sugar_lift_py_tests.floor.call_site_value import (
        carries_its_stores_to_the_caller,
    )

    if (
        isinstance(value, CallSiteValue)
        and carries_its_stores_to_the_caller(value)
        and value.retained_source_completion_outcome() is None
    ):
        # No completion kept: apply the call the one way, through
        # ``producer_outcome`` (#7757 entry 6) -- native operations
        # discharge against the bound actuals and the body's raises are
        # the Call's own.  Each completed face is the Call carrying the
        # stores its body made; the statement lays them in its record.
        def applied(result):
            _walrus, more = caller_stores_of(peel_walrus_binds(result)[0])
            return ExitSet.completed(
                BlockValue((recorded, *stores, *more), can_fall_through=True)
            )

        return value.producer_outcome(ctx).and_then(applied)
    return ExitSet.completed(BlockValue((recorded, *stores), can_fall_through=True))
