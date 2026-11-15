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
        # The returned value is this statement's header: every write it
        # carries -- a walrus's bind (``return (x := 5) + 1``), and what a
        # call in it did to objects this frame shares with its caller (the
        # callee's stores and the rest of the one projection,
        # ``call_site_value.caller_visible_values``) -- reaches the record
        # the ``return`` leaves by the one header rule (``header_applied``,
        # ``header_ran``), as a call in statement position lays them
        # (``record_statement_value``): the stores first in the record, so
        # the caller of this frame reads them there
        # (``caller_visible_stores``), and every write in the context the
        # record leaves, where what the frame left of each shared object is
        # read (``_left_here``, and the read where the body ends,
        # ``SourceVisibleFunctionBodySugar.left_in``).  ``h`` returning
        # ``g(a)`` leaves ``a`` as ``g`` left it.  The return holds the value
        # the header presents beneath its writes.
        from sugar_lift_py_tests.caller_parameter_contract import (
            NativeOperationExitCarrierV1,
        )
        from sugar_lift_py_tests.floor.object_identity import arrived
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            header_applied,
            header_ran,
        )

        headed, valued = header_applied(self, "value", ctx)
        if headed is not None:
            return headed
        if isinstance(valued, NativeOperationExitCarrierV1):
            # A value whose completion waits on the caller's actuals takes
            # the same step on the value it discharges to.
            return valued.and_then(lambda value: header_ran(self, "value", value, ctx))

        def returned(value):
            # The caller holds the returned value by binding: what this frame
            # made is not current in the caller's (``object_identity``).
            result = ReturnValue(arrived(value, self.site))
            # What the frame left of each object it shares with a caller, on
            # the arm that leaves here (the header's writes, where it carried
            # any, are already in ``ctx``: ``header_ran``).
            left = self._left_here(ctx)
            if not left:
                return ExitSet.completed(result)
            return ExitSet.completed(BlockValue((*left, result), can_fall_through=True))

        return valued.and_then(returned)

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
