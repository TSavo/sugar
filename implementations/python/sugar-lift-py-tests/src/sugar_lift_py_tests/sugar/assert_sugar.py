from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import ClassVar

from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class AssertSugar(Sugar):
    """`assert <test>[, <message>]`. It desugars the test, and the
    result states itself: a symbolic predicate states an inv (the fact the
    record emits -- first encounter a fact to discharge, a later consumer
    meets it as a warrant, a constraint; that duality is protocol position,
    never this sugar's), ground True states nothing, ground False is the
    named halt. The sugar owns no distinction; the value answers.

    Message disposition (#4593 / #4594): the optional second operand is
    diagnostic packaging for AssertionError, not part of the proposition.
    CPython evaluates it only on the failing path. Even when the message is
    a runtime expression (`assert x, f(y)`), any effects of that evaluation
    are unobserved by the claim membrane (paper 26: unsworn effects are
    silence). The lift MUST NOT invent a conditional py.* effect gated on
    ¬test. Spelling rides `assertMessage` provenance on the source
    memento; AssertSugar never builds or reduces the message operand.
    """

    test: Sugar
    site: object = dataclass_field(compare=False)
    message: object | None = dataclass_field(compare=False, default=None)
    # Whether the message holds a walrus (``assert c, (m := f())``). The
    # message is never reduced here, but CPython runs it before it raises
    # ``AssertionError``, so its walrus is bound when the assert halts:
    # ``holds_a_walrus`` reads this, and the statement's failure, offering
    # no record that holds the bind, is refused by name
    # (``_require_recorded_halts``), never given the prefix that drops it.
    message_holds_a_walrus: bool = dataclass_field(compare=False, default=False)
    # A simple statement: it evaluates its test, then completes or halts,
    # binding nothing before its own halt but what a walrus in its test or
    # message binds. A halted arm of a walrus-free test halted at the head of
    # the statement, so the enclosing block's prefix is its record
    # (``reduce_block_to_exitset``), as for every expression statement.
    halts_at_statement_head: ClassVar[bool] = True

    @classmethod
    def witnesses(cls):
        # The stated inv IS the discriminator: the truthful twin's assert holds
        # in the body's universe, the lying twin's contradicts it.
        return _call_pair(
            name="assert_return",
            owner_sugar="AssertSugar",
            truthful=(
                "def A(z):\n    return z\n\n" "def test_a():\n    assert A(5) == 5\n"
            ),
            lying=(
                "def A(z):\n    return z\n\n" "def test_a():\n    assert A(5) == 6\n"
            ),
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        # Desugar the test, and the result states itself. The outcome is
        # recorded for the readers of this assert (item 28, #7757): they read
        # it off the owner's one reduction and never reduce the assert alone.
        from sugar_lift_py_tests import assert_reductions
        from sugar_lift_py_tests.floor.named_expression_value import (
            consume_operands,
        )

        # The assert's own step (the test stated, ``AssertionError`` where
        # it fails) runs after its test: it consumes the test through the
        # one operand door, so it states the value the test presents, and
        # its failure after a walrus in the test bound (``assert (a :=
        # f())``) carries the record of this statement's context with the
        # bind applied (``consume_operands``), never the block's prefix,
        # which holds none of it.
        outcome = self.test.desugar(ctx).and_then(
            lambda value: consume_operands(
                lambda presented: presented.stated(self.site), value
            )
        )
        assert_reductions.record(self.site, outcome)
        return outcome
