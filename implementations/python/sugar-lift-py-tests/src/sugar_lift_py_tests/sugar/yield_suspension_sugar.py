from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class YieldSuspensionSugar(Sugar):
    """``yield <value>``: a suspension of the generator frame, reduced where
    the body runs (#7757 step 6).

    A generator function's call runs none of its body: it is its
    definition's coordinate and edge, joined at prove, and its contract
    states no result and no halt of the call (``UniverseValue.suspends``,
    ``tree_enumerate.reduction_rows``).  The body is still the one body,
    reduced once by the one block reduction, and a ``yield`` is one of its
    operations: its operand is evaluated (every halt it takes kept), then
    control passes to whoever resumes the generator -- ``next``, ``send``,
    ``throw``, ``close`` -- code nothing here follows, as an unfollowed call
    is.  What the frame holds is exposed there by the one exposure rule
    (``container_mutation._sites_at``, #8158), and what the suspension
    hands back is the one two-faced undecided operation
    (``ExitSet.two_faced``): it completes with ``python:yield_result(<key>)``
    -- the value ``send`` handed in, ``None`` for ``next``, never named
    here -- under ``python:yield_op.completes``, and halts with an
    ``UndeterminedRaiseEffect`` under the complement (``throw`` raises its
    exception at the ``yield``, ``close`` raises ``GeneratorExit`` there).
    Both faces owe the ``undecided`` member at the yield's site.  The key is
    the occurrence key where the yield evaluates, so two suspensions (two
    items of a live loop) are two unknowns.

    What a consumer reads off the generator -- its items, its return value
    as ``StopIteration``'s -- is the consumer's iteration over the call's
    result: the one undecided ``iter``/``next`` read, two faces, owed
    (``FloorValue.undecided_iteration``, ``undecided_next``), whose halted
    face covers every halt this body may take when resumed."""

    value: Sugar | None
    site: object = field(compare=False)

    @classmethod
    def witnesses(cls):
        from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing

        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="SymbolicValue",
            reason=(
                "a yield's resumed value is the undecided read; the claims it "
                "bears are the body's after it "
                "(test_generator_body_reduces_through_its_yields_twins_7757)"
            ),
        )

    def desugar(self, ctx=None):
        from sugar_lift_py_tests.floor.named_expression_value import (
            consume_operands,
        )

        if self.value is None:
            return self._resumed()
        # The operand runs first, its halts kept; the suspension follows on
        # its completed faces through the one operand door, so a walrus in
        # the operand binds before the resume and rides its result.
        return self.value.desugar(ctx).and_then(
            lambda value: consume_operands(lambda _value: self._resumed(), value)
        )

    def _resumed(self):
        """What the suspension hands back where the generator is resumed:
        the one two-faced undecided operation, keyed where it evaluates
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
            _siteless_undecided_read("YieldSuspensionSugar", "yield", "Yield")
        key = occurrence_key(self.site)
        term, completes = undecided_result_terms("yield", (), key)
        return ExitSet.two_faced(
            SymbolicValue(term),
            UndeterminedRaiseEffect(
                blame=str(self.site),
                occurrence=key,
                producer_node_owner="YieldSuspensionSugar",
                site=self.site,
            ),
            guard=completes,
            site=self.site,
        )
