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
    """

    halts_at_statement_head: ClassVar[bool] = True

    value: object | None  # expression sugar, or syntactic empty return
    site: object = dataclass_field(compare=False)

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
        if self.value is None:
            from sugar_lift_py_tests.floor import NoneValue

            return ExitSet.completed(ReturnValue(NoneValue()))
        # The returned value is this statement's header: every write it
        # carries -- a walrus's bind (``return (x := 5) + 1``), and the
        # receiver field stores a call in it carried
        # (``call_site_value.caller_visible_stores``) -- reaches the record
        # the ``return`` leaves by the one header rule (``header_applied``,
        # ``header_ran``), as a call in statement position lays them
        # (``record_statement_value``).  The return holds the value the
        # header presents beneath its writes.
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
            return ExitSet.completed(ReturnValue(arrived(value, self.site)))

        return valued.and_then(returned)
