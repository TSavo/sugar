from __future__ import annotations

from dataclasses import dataclass, field, replace

from sugar_lift_py_tests.floor.floor_value import FloorValue
from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.function_universe_sugar import (
    _ReducedBlock,
    block_values,
    reduce_block_to_exitset,
)
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing


@dataclass(frozen=True)
class CallerVisibleStateValue(FloorValue):
    """What a callee's frame left of an object it shares with its caller,
    where one arm of its body left: the read of the object there
    (``SourceVisibleFunctionBodySugar.exit_reads``) reduced in the context
    that arm ended in, or None where that arm does not decide it.

    An entry of the callee's record, as the receiver field stores it made
    are: the call carries it out to its caller, on that arm, under the
    call's key and ``label`` (``call_site_value.caller_visible_values``), the
    one projection of what a callee did to what its caller sees.  ``frame``
    is the body that left it: a call carries only its own body's.  It
    states nothing and binds nothing in the callee's frame."""

    label: str
    value: FloorValue | None
    frame: object = field(default=None, compare=False, repr=False)

    def guarded(self, formula):
        # Testimony for the call that carries it, never a fact of the record
        # it sits in: a guard over that record leaves it as it is.
        del formula
        return self

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        del owner
        return ctor("python:caller-visible-state", (str_const(self.label),))


@dataclass(frozen=True)
class SourceVisibleFunctionBodySugar(Sugar):
    """Already-constructed statement Sugars for one source-visible call frame.

    ``exit_reads`` (``nodes._exit_reads``): ``((label, read, keys), ...)``,
    the read, where the body ends, of each object the frame shares with a
    caller that the body changed, and the evaluations it reads through.
    Every arm the body leaves by -- each completed record and each halt's
    record -- carries each one as an entry (``CallerVisibleStateValue``): the
    read reduced in the context the arm ended in where that context holds
    every one of its keys (every statement that made the state completed
    there), else undecided.  The call carries them to its caller
    (``call_site_value.caller_visible_values``)."""

    statements: tuple[object, ...]
    site: object = field(compare=False)
    exit_reads: tuple = field(default=(), compare=False)

    @classmethod
    def witnesses(cls):
        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="BlockValue",
            reason="call-frame bodies project the ordinary constructed block",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        exits = reduce_block_to_exitset(self.statements, ctx)
        if self.exit_reads:
            exits = self._leaving(exits)
        return block_values(exits)

    def _leaving(self, exits):
        """``exits`` with every record it leaves by carrying what the frame
        left of each shared object there (``left_in``)."""
        from sugar_lift_py_tests.caller_parameter_contract import (
            NativeOperationExitCarrierV1,
        )

        def completed(state):
            return ExitSet.completed(self.left_in(state))

        if isinstance(exits, NativeOperationExitCarrierV1):
            return exits.and_then(completed)
        return exits.sequence(
            completed,
            consume=lambda halt: ExitSet.halted(
                halt.effect, state=self.left_in(halt.state)
            ),
        )

    def left_in(self, state):
        """``state`` (a record one arm left by) with an entry for each exit
        read (``CallerVisibleStateValue``); anything that is no record is
        handed back as it is."""
        if not isinstance(state, _ReducedBlock):
            return state
        left = tuple(
            CallerVisibleStateValue(label, self._left(read, keys, state.context), self)
            for label, read, keys in self.exit_reads
        )
        return replace(state, entries=(*state.entries, *left))

    @staticmethod
    def _left(read, keys, context):
        """``read`` reduced in ``context``: its one plain completed value,
        where ``context`` holds every key it reads through; None (undecided)
        anywhere else -- a statement that made the state did not complete
        on this arm, or the read itself does not decide one value."""
        from sugar_lift_py_tests.floor.named_expression_value import (
            peel_walrus_binds,
        )
        from sugar_lift_py_tests.sugar.evaluation_ref_sugar import (
            evaluation_read_here,
        )
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            plain_completed_value,
        )

        temporal = getattr(context, "temporal", None)
        if temporal is None or any(
            temporal.value_if_bound(evaluation_read_here(temporal, key)) is None
            for key in keys
        ):
            return None
        value = plain_completed_value(read.desugar(context))
        if value is None:
            return None
        value = peel_walrus_binds(value)[1]
        if not isinstance(value, FloorValue) or not value.follow_rest().continues:
            return None
        return value
