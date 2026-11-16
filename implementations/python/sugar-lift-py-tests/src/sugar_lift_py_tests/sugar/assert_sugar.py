from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import ClassVar

from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _assertion_pair


def halts_where_its_asserts_fail(block, outcome) -> ExitSet:
    """``outcome`` (what one completed face of a function body goes on to)
    beneath each ``assert`` that face stated, as Python runs it: an
    ``assert`` whose test is false raises ``AssertionError`` there, so the
    body never reaches ``outcome`` (#7757: a halt is never dropped).

    THE rule for "an ``assert`` is a halt", one for every body: a function's
    own universe (``FunctionUniverseSugar.desugar``, each completed arm's
    record) and the class call that runs ``__init__`` in place
    (``ClassConstructorBodySugar.desugar``, each completed initializer
    face's record).  A symbolic ``assert`` states its test as a fact
    (``InvValue``, ``AssertSugar``) and has no failing arm where it stands;
    the fact stays the claim of the function whose body it is.  Left there
    alone, the fact was the callee's ``inv``, which no caller reads: prove
    joins a call to the callee's ``post`` and its ``panicLoci`` only, so
    ``f(-1)`` over ``assert n > 0`` completed at prove.  Each fact, in the
    order the face stated them, is the split ``if not <test>: raise
    AssertionError`` is: the body halts with ``AssertionError`` at the
    ``assert`` (``ground_assertion_error``, the exit a test stated False
    takes) under the fact's complement, and goes on under the fact to the
    next one, then to ``outcome``.  Each halt is a halted arm of the body's
    one reduction, so its contract states it as a panic locus
    (``tree_enumerate.halt_locus``) whose raised type is ``AssertionError``
    (a caller's ``except AssertionError`` takes it), and the completed arm
    holds the fact as before: the assertion row is still the function's
    claim (``exit_arms_payload_rows``).

    Only an ``assert`` statement's fact is one: the fact is sited at the
    ``assert`` (``AssertSugar.site``), as ``tree_enumerate.
    halted_assertion_sites`` reads it.  Any other fact a record holds (a
    loop's recurrence, a resource binding) states what a value is, never a
    test that can fail.  A test the reduction decided true states the fact
    ``true``: it cannot fail, so it is no split."""
    from sugar_lift_py_tests.floor.ground_assertion_error import (
        ground_assertion_error,
    )
    from sugar_lift_py_tests.floor.inv_value import InvValue
    from sugar_lift_py_tests.outcome.exit_set import (
        _is_true,
        complement_guard,
        partition,
    )
    from sugar_source_tree.nodes import Assert

    facts = tuple(
        statement
        for statement in block.statements
        if isinstance(statement, InvValue)
        and isinstance(getattr(statement.site, "node", None), Assert)
        and not _is_true(statement.formula)
    )
    for fact in reversed(facts):
        fails, holds = partition(("AssertSugar.fails", fact.site, fact.formula))
        outcome = (
            ground_assertion_error(site=fact.site)
            .guarded(complement_guard(fact.formula), fails)
            .union(outcome.guarded(fact.formula, holds))
        )
    return outcome


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
    Its sugar is built with the statement, as every child's is (a message
    that has none refuses the assert by name at construction); CPython
    evaluates it only on the failing path, before it raises: so here too
    it is evaluated only beneath the assert's own failure (the
    ``AssertionError`` a test stated False raises), through the one
    expression evaluation, after the test's writes. What it does there is
    what the halt leaves with: a call's stores and a walrus's bind in the
    halt's record (``_stated``), a halt of its own in place of the
    ``AssertionError``. The lift never invents a conditional py.* effect
    gated on ¬test: a symbolic test states its inv and has no failing arm
    here, and the success path never evaluates the message. The body whose
    record holds the fact halts where it fails
    (``halts_where_its_asserts_fail``).
    Spelling rides `assertMessage` provenance on the source memento.
    """

    test: Sugar
    site: object = dataclass_field(compare=False)
    # The message's sugar, built at construction with the test's
    # (``Assert._construct_sugar``). It is part of what the statement is: a
    # walrus in it is bound when the assert fails, and ``holds_a_walrus``
    # reads it here as it reads every compared child.
    message: Sugar | None = None
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
        return _assertion_pair(
            name="assert_return",
            owner_sugar="AssertSugar",
            statements="z = 5",
            truthful="z == 5",
            lying="z == 6",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        # Desugar the test, and the result states itself. The stated fact
        # reaches the proof only as a row of the owner's one reduction
        # (item 28, #7757); the assert is never reduced alone.
        #
        # The test is this statement's header: a walrus bind or callee store
        # its value carried reaches what follows the assert, and a failure
        # after it, by the one header rule (``header_applied``), the stores
        # laid in the record.  There the assert runs again on the value the
        # test presents (``header_ran``): the stated fact, in the context the
        # test's writes left.
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            header_applied,
        )

        headed, tested = header_applied(self, "test", ctx)
        if headed is not None:
            return headed
        # Where the test stated False, the message runs before the
        # ``AssertionError``, in the context the test's writes left (this
        # run's ``ctx``: ``header_ran`` ran it there) (``_stated``).
        return tested.and_then(lambda value: self._stated(value, ctx))

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
            self.message is None
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
            return self.message.desugar(ctx).and_then(
                lambda value: raised(halt, value)
            )

        return stated.and_then(ExitSet.completed, consume=failing)
