"""`await <awaitable>` -- the operand, then the one undecided read."""

from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class AwaitSugar(Sugar):
    """``await <value>``: the operand runs, then the awaited object runs
    code nothing here follows (#7757 step 6).

    Calling an ``async def`` runs none of its body and returns a coroutine
    object; its contract states no result and no halt of the call
    (``UniverseValue.suspends``, ``tree_enumerate.reduction_rows``), as a
    generator function's does.  The body runs where the coroutine is
    awaited: ``await`` calls the operand's ``__await__`` and drives it --
    the coroutine's body, a ``Future``'s, any awaitable's -- to its
    ``StopIteration``, whose value is the ``await``'s result.  Nothing here
    joins that body: what the coroutine's contract would state of it is the
    call's ``out``, which it does not state.  So the ``await`` is the one
    two-faced undecided operation (``ExitSet.two_faced``, through
    ``undecided_result_terms``): it completes with
    ``python:await_result(<key>)`` under ``python:await_op.completes`` and
    halts with an ``UndeterminedRaiseEffect`` under the complement (the
    awaited body's own halts, a ``TypeError`` for an operand that is no
    awaitable, a cancellation), both faces owing the ``undecided`` member at
    the await's site.  The key is the occurrence key where the ``await``
    evaluates, so two awaits (two items of a live loop) are two unknowns.

    The operand is evaluated first through the one operand door
    (``consume_operands``): every halt it takes is kept, and a walrus in it
    binds before the await.  What the frame holds is exposed to the awaited
    code by the one exposure rule (``container_mutation._sites_at``,
    ``Await``)."""

    value: Sugar
    site: object = field(compare=False)

    @classmethod
    def witnesses(cls):
        from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing

        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="SymbolicValue",
            reason=(
                "an await's result is the undecided read; the claims it "
                "bears are the body's after it "
                "(test_async_call_returns_a_coroutine_twins_7757)"
            ),
        )

    def desugar(self, ctx=None):
        from sugar_lift_py_tests.floor.named_expression_value import (
            consume_operands,
        )

        # The operand runs first, its halts kept; the await follows on its
        # completed faces through the one operand door.
        return self.value.desugar(ctx).and_then(
            lambda value: consume_operands(lambda _value: self._awaited(), value)
        )

    def _awaited(self):
        """What the awaited object hands back: the one two-faced undecided
        operation, keyed where the ``await`` evaluates
        (``floor_value.undecided_result_terms``)."""
        from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
        from sugar_lift_py_tests.floor.floor_value import (
            _siteless_undecided_read,
            undecided_result_terms,
        )
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
        from sugar_lift_py_tests.occurrence import occurrence_key
        from sugar_lift_py_tests.outcome.exit_set import ExitSet

        if self.site is None:
            _siteless_undecided_read("AwaitSugar", "await", "Await")
        key = occurrence_key(self.site)
        term, completes = undecided_result_terms("await", (), key)
        return ExitSet.two_faced(
            SymbolicValue(term),
            UndeterminedRaiseEffect(
                blame=str(self.site),
                occurrence=key,
                producer_node_owner="AwaitSugar",
                site=self.site,
            ),
            guard=completes,
            site=self.site,
        )
