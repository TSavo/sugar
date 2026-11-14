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
        # The returned value is what the frame answers.  A walrus inside it
        # (``return (x := 5) + 1``) wrote this frame's name, which no reader
        # after the return sees: the return holds the value it presents, so
        # the bind never reaches the caller's temporal as a write of the
        # caller's own name.
        from sugar_lift_py_tests.floor.named_expression_value import (
            peel_walrus_binds,
        )
        from sugar_lift_py_tests.floor.object_identity import arrived

        # The caller holds the returned value by binding: what this frame
        # made is not current in the caller's (``object_identity``).
        return self.value.desugar(ctx).and_then(
            lambda value: ExitSet.completed(
                ReturnValue(arrived(peel_walrus_binds(value)[1]))
            )
        )
