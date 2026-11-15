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
    where one arm of its body left: the read of the object there reduced in
    the context that arm ended in, or None where that arm does not decide
    it.  A ``return`` lays its own, read where it stands (``at_return``,
    ``ReturnSugar.exit_reads``); every other arm the read where the body
    ends (``SourceVisibleFunctionBodySugar.exit_reads``).

    An entry of the callee's record, as the receiver field stores it made
    are: the call carries it out to its caller, on that arm, under the
    call's key and ``label`` (``call_site_value.caller_visible_values``), the
    one projection of what a callee did to what its caller sees.  ``frame``
    is the token of the frame that left it: a call carries only its own
    frame's.  ``guards``: the branch conditions on the way to the ``return``
    that laid it, as its ``GuardedReturn`` has them -- a record that holds
    the arms of several ``return`` statements and of the end holds each
    one's under its own guards, and the call selects among them.  It states
    nothing and binds nothing in the callee's frame."""

    label: str
    value: FloorValue | None
    frame: object = field(default=None, compare=False, repr=False)
    guards: tuple = ()
    at_return: bool = field(default=False, compare=False)

    def guarded(self, formula):
        # The branch a ``return`` stood in, stacked as its ``GuardedReturn``
        # stacks it; a guard that is truth selects nothing.
        from sugar_lift_py_tests.outcome.exit_set import _is_true

        if _is_true(formula):
            return self
        return replace(self, guards=(formula, *self.guards))

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
    record -- carries each one as an entry (``CallerVisibleStateValue``): a
    ``return``'s arm the read where it stood, which the ``return`` laid
    (``ReturnSugar.exit_reads``); every other arm the read where the body
    ends, reduced in the context the arm ended in where that context holds
    every one of its keys (every statement that made the state completed
    there), else undecided.  The call carries them to its caller
    (``call_site_value.caller_visible_values``).  ``frame``: the frame's
    token (``CallerVisibleStateValue.frame``).  ``returns_read``: the body
    leaves by a ``return`` before its end, and every ``return`` of its own
    lays its read (``nodes.FrameReturn``); else the read where the body
    ends is every arm's."""

    statements: tuple[object, ...]
    site: object = field(compare=False)
    exit_reads: tuple = field(default=(), compare=False)
    frame: object = field(default=None, compare=False)
    returns_read: bool = field(default=False, compare=False)

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
        return exits.and_then(
            completed,
            consume=lambda halt: ExitSet.halted(
                halt.effect, state=self.left_in(halt.state)
            ),
        )

    def left_in(self, state):
        """``state`` (a record one arm left by) with what the frame left of
        each exit read's object on every path the record holds; anything
        that is no record is handed back as it is.

        Where the body leaves by a ``return`` before its end
        (``returns_read``), each ``return`` the record holds laid its own
        read (``CallerVisibleStateValue.at_return``), under that
        ``return``'s guards, and the read where the body ends is laid for
        the rest of the record's paths -- none where a ``return`` laid one
        unguarded (the record is that ``return``'s arm).  Where the record
        holds a ``return`` that laid none for the object, what the frame
        left of it is not stated on that path: the object is undecided on
        every path of the record.  Elsewhere no arm leaves before the end,
        and the read where the body ends is every path's."""
        if not isinstance(state, _ReducedBlock):
            return state
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            _is_return_entry,
        )

        returns = sum(
            1
            for entry in state.entries
            if _is_return_entry(entry)
            and not isinstance(entry, CallerVisibleStateValue)
        )
        entries = list(state.entries)
        for label, read, keys in self.exit_reads:
            laid = [
                entry
                for entry in entries
                if isinstance(entry, CallerVisibleStateValue)
                and entry.at_return
                and entry.frame == self.frame
                and entry.label == label
            ]
            if self.returns_read and len(laid) != returns:
                entries = [
                    entry
                    for entry in entries
                    if not any(entry is other for other in laid)
                ]
                entries.append(CallerVisibleStateValue(label, None, self.frame))
                continue
            if any(not entry.guards for entry in laid):
                continue
            entries.append(
                CallerVisibleStateValue(
                    label, self._left(read, keys, state.context), self.frame
                )
            )
        return replace(state, entries=tuple(entries))

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
