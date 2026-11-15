from __future__ import annotations

from typing import ClassVar

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.floor import ReturnValue
from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class ReturnSugar(Sugar):
    """The `return <expr>` statement. Reduce the value; the result is a
    ReturnValue carrying that reduced floor. The block carries it as an exit,
    and the universe's post projects `out == <return term>` from it.

    Meaning-only, node-constructed.  ``value=None`` is the syntax-owned bare
    return arm and constructs Python's existing ``NoneValue`` floor.

    ``exit_reads`` (a followed call frame's ``return``,
    ``nodes.FrameReturn``): ``((label, read, keys), ...)``, the read where
    the ``return`` stands of each object the frame shares with a caller --
    ``read`` None where it does not decide it there.  The arm that leaves by
    this ``return`` carries each one (``CallerVisibleStateValue``), read in
    the context the returned value left, as every other arm carries the read
    where the body ends (``SourceVisibleFunctionBodySugar``); ``frame`` is
    the frame's token.
    """

    halts_at_statement_head: ClassVar[bool] = True

    value: object | None  # expression sugar, or syntactic empty return
    site: object = dataclass_field(compare=False)
    exit_reads: tuple = dataclass_field(default=(), compare=False)
    frame: object = dataclass_field(default=None, compare=False)

    @classmethod
    def witnesses(cls):
        prefix = "def A(z):\n    return z\n\n"
        return _call_pair(
            name="return_value",
            owner_sugar="ReturnSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(5) == 0\n",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        from sugar_lift_py_tests.floor.block_value import BlockValue

        if self.value is None:
            from sugar_lift_py_tests.floor import NoneValue

            result = ReturnValue(NoneValue())
            left = self._left_here(ctx)
            if not left:
                return ExitSet.completed(result)
            return ExitSet.completed(BlockValue((*left, result), can_fall_through=True))
        # The returned value is what the frame answers.  A walrus inside it
        # (``return (x := 5) + 1``) wrote this frame's name, which no reader
        # after the return sees: the return holds the value it presents, so
        # the bind never reaches the caller's temporal as a write of the
        # caller's own name.
        #
        # A store a callee the value called made on an object the caller sees
        # (``CallerStoreValue``) is not this frame's: it is laid in the record
        # before the return, as a statement alone lays it
        # (``record_statement_value``), so the caller of this frame reads it
        # there (``caller_visible_stores``) and never misses it.
        from sugar_lift_py_tests.floor.named_expression_value import (
            caller_stores_of,
            peel_walrus_binds,
            written_by,
        )
        from sugar_lift_py_tests.floor.object_identity import arrived

        def returned(value):
            binds, presented = peel_walrus_binds(value)
            _walrus, stores = caller_stores_of(binds)
            # The caller holds the returned value by binding: what this frame
            # made is not current in the caller's (``object_identity``).
            result = ReturnValue(arrived(presented, self.site))
            # What the frame left of each object it shares with a caller, on
            # the arm that leaves here: read after the value, whose own calls
            # may have changed it.
            left = self._left_here(written_by(value, ctx))
            if not stores and not left:
                return ExitSet.completed(result)
            return ExitSet.completed(
                BlockValue((*stores, *left, result), can_fall_through=True)
            )

        return self.value.desugar(ctx).and_then(returned)

    def _left_here(self, at) -> tuple:
        """Each exit read reduced in ``at`` (the context this ``return``
        leaves the frame in), as the entry the arm carries
        (``CallerVisibleStateValue``, ``at_return``); undecided where the
        ``return`` does not decide it."""
        if not self.exit_reads:
            return ()
        from sugar_lift_py_tests.sugar.source_visible_function_body_sugar import (
            CallerVisibleStateValue,
            SourceVisibleFunctionBodySugar,
        )

        return tuple(
            CallerVisibleStateValue(
                label,
                None
                if read is None
                else SourceVisibleFunctionBodySugar._left(read, keys, at),
                self.frame,
                at_return=True,
            )
            for label, read, keys in self.exit_reads
        )
