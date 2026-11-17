"""`yield from <iterable>` — delegated generator suspension."""

from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class YieldFromSugar(Sugar):
    """``yield from <iterable>``: a delegation of the generator frame to a
    sub-iterator, reduced where the body runs (#7757 step 6).

    A generator function's call runs none of its body (``UniverseValue.
    suspends``); the body is the one body, reduced once, and a ``yield
    from`` is one of its operations, built from the operations it is made
    of, each the one way it already is:

    - the operand is evaluated first through the one operand door
      (``consume_operands``): every halt it takes is kept, and a walrus in
      it binds before the delegation;
    - ``iter(<operand>)`` is the one ``iter`` operation (``iterated``,
      ``IteratorOperation``), submitted to the receiver, which owns the
      answer: the undecided read for a formal or a call's result, nothing
      submitted where iterating is decided never to raise; its raised face
      leaves before anything is delegated;
    - a step of the sub-iterator is the one ``next`` operation (``stepped``,
      ``NextOperation``): its halt other than ``StopIteration`` is kept;
    - what the delegation hands back -- the sub-iterator's
      ``StopIteration`` value once the consumer has resumed it through every
      item, or what ``send``/``throw``/``close`` passed in -- is the one
      two-faced undecided operation (``suspension_resumed``, as a ``yield``'s
      resume is): it completes with ``python:yield_from_result(<key>)``
      under ``python:yield_from_op.completes`` and halts with an
      ``UndeterminedRaiseEffect`` under the complement, both faces owing the
      ``undecided`` member at the ``yield from``'s site.  The key is the
      occurrence key where it evaluates, so two delegations are two
      unknowns.

    What the frame holds is exposed to the consumer by the one exposure
    rule (``container_mutation._sites_at``, ``_SUSPENSION_KINDS``)."""

    value: object  # the iterable's sugar
    site: object = field(compare=False)

    @classmethod
    def witnesses(cls):
        from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing

        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="SymbolicValue",
            reason=(
                "a yield from's delegated result is the undecided read; the "
                "claims it bears are the body's after it "
                "(test_yield_from_delegates_through_iter_and_next_twins_7757)"
            ),
        )

    def desugar(self, ctx=None):
        from sugar_lift_py_tests.floor.named_expression_value import (
            consume_operands,
        )

        # The operand runs first, its halts kept; the delegation follows on
        # its completed faces through the one operand door.
        return self.value.desugar(ctx).and_then(
            lambda value: consume_operands(
                lambda iterable: self._delegated(iterable, ctx), value
            )
        )

    def _delegated(self, iterable, ctx):
        """``iter`` of the operand, one ``next`` step of the sub-iterator,
        then the resume (``suspension_resumed``)."""
        from sugar_lift_py_tests.operations.iterator_operation import (
            iterated,
            stepped,
        )
        from sugar_lift_py_tests.outcome.exit_set import _require_exit_set
        from sugar_lift_py_tests.sugar.yield_suspension_sugar import (
            suspension_resumed,
        )

        owner = "YieldFromSugar"

        def resumed():
            return suspension_resumed(
                self.site, name="yield_from", owner=owner, node="YieldFrom"
            )

        return _require_exit_set(
            iterated(iterable, ctx, owner=owner, site=self.site),
            owner=f"{owner}.iter",
        ).and_then(
            lambda iterator: stepped(
                iterable, iterator, ctx, resumed, owner=owner, site=self.site
            )
        )
