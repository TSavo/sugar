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
    CPython evaluates it only on the failing path, before it raises: so
    here too it is evaluated only beneath the assert's own failure (the
    ``AssertionError`` a test stated False raises), through the one
    expression evaluation, after the test's writes. What it does there is
    what the halt leaves with: a call's stores and a walrus's bind in the
    halt's record (``_stated``), a halt of its own in place of the
    ``AssertionError``. The lift never invents a conditional py.* effect
    gated on ¬test: a symbolic test states its inv and has no failing arm
    here, and the success path never builds or evaluates the message.
    Spelling rides `assertMessage` provenance on the source memento.
    """

    test: Sugar
    site: object = dataclass_field(compare=False)
    message: object | None = dataclass_field(compare=False, default=None)
    # Whether the message holds a walrus (``assert c, (m := f())``). CPython
    # runs the message before it raises ``AssertionError``, so its walrus is
    # bound when the assert halts: ``holds_a_walrus`` reads this, and a
    # failure that offers no record holding the bind is refused by name
    # (``_require_recorded_halts``), never given the prefix that drops it.
    message_holds_a_walrus: bool = dataclass_field(compare=False, default=False)
    # The message's sugar, constructed where the assert fails and nowhere
    # else (``Assert._construct_sugar``: the node's own ``sugar``): a
    # message the success path never runs (``assert c, (yield 1)``) is never
    # built, and one that cannot be built is refused where it would run.  A
    # lookup aid, never testimony: the message is testified by its fragment
    # (``message``), and this reads its sugar out of the node it names.
    message_sugar: object | None = dataclass_field(
        compare=False, default=None, metadata={"testimony": "lookup"}
    )
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
        #
        # The test is this statement's header: a walrus bind or callee store
        # its value carried reaches what follows the assert, and a failure
        # after it, by the one header rule (``header_applied``), the stores
        # laid in the record.  There the assert runs again on the value the
        # test presents (``header_ran``), and that run records its own
        # outcome: the stated fact, in the context the test's writes left.
        from sugar_lift_py_tests import assert_reductions
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            header_applied,
        )

        headed, tested = header_applied(self, "test", ctx)
        if headed is not None:
            return headed
        # Where the test stated False, the message runs before the
        # ``AssertionError``, in the context the test's writes left (this
        # run's ``ctx``: ``header_ran`` ran it there) (``_stated``).
        outcome = tested.and_then(lambda value: self._stated(value, ctx))
        assert_reductions.record(self.site, outcome)
        return outcome

    def _stated(self, presented, ctx):
        """``presented`` (the test's value) stated, and beneath the assert's
        own failure, the message evaluated in ``ctx`` (the test's writes
        applied) before ``AssertionError`` is raised, as CPython does.

        The message is an expression evaluated after the test: it goes
        through the one expression evaluation (``desugar``).  A halt of it
        leaves in place of the ``AssertionError`` (CPython never reaches
        the raise), carrying its own record, or recorded where the test's
        writes left (``header_ran``) or at the statement's head.  Where it
        completes, the ``AssertionError`` halts after what it did: the
        record where its writes left (``halt_record`` of ``written_by``),
        its callee stores first in the entries (``laid_in_record``), as a
        header's writes reach the rest of its statement (``header_ran``),
        which lays the test's stores before them.  A message that wrote
        nothing leaves the halt as it was.  Any other halt of the step (a
        truth test that raises) is not the assert's failure and stands as
        it is."""
        stated = presented.stated(self.site)
        if (
            self.message_sugar is None
            or not isinstance(stated, ExitSet)
            or not stated.halts()
        ):
            return stated
        from sugar_lift_py_tests.floor.ground_assertion_error import (
            ground_assertion_error,
        )
        from sugar_lift_py_tests.floor.named_expression_value import (
            caller_stores_of,
            peel_walrus_binds,
            written_by,
        )
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            halt_record,
            laid_in_record,
        )

        (failure,) = ground_assertion_error(site=self.site).halts()

        def raised(halt, value):
            binds, _presented = peel_walrus_binds(value)
            if not binds:
                return ExitSet.halted(halt.effect, state=halt.state)
            _walrus, stores = caller_stores_of(binds)
            return laid_in_record(
                stores,
                ExitSet.halted(
                    halt.effect, state=halt_record(written_by(value, ctx))
                ),
            )

        def failing(halt):
            if halt.effect != failure.effect:
                return None
            return self.message_sugar().desugar(ctx).and_then(
                lambda value: raised(halt, value)
            )

        return stated.sequence(ExitSet.completed, consume=failing)
