from __future__ import annotations

from dataclasses import dataclass, field, replace

from .floor_value import FloorValue


@dataclass(frozen=True)
class NamedExpressionValue(FloorValue):
    """The inseparable value and temporal-bind faces of ``(name := value)``.

    Comparison is Floor-owned through the **presented** face: this value only
    contributes its temporal bind via ``_carry``. Left-hand ops dispatch to
    ``presented_value.<op>(other)``; right-hand routing is operator-owned typed
    double-dispatch (``less_than_from_left``, …). No ``predicate_from_left(str)``.
    """

    name: str
    assigned_value: FloorValue
    presented_value: FloorValue = field(init=False)
    # The coordinate of the walrus's one evaluation (``NamedExpr.substitute``).
    # ``extend_scope`` binds the assigned value under it, never under the
    # name: every later read substitution rewrote is an ``EvaluationRef`` to it
    # (temporal choice 1, #7661), a branch of the ``if``, ``while`` or
    # conditional expression whose test holds the walrus included.
    evaluation: str | None = None
    # The walrus did not run on this arm of a conditional expression
    # (``a if c else (x := 5)`` where ``c`` held): under its key the name
    # holds the value it had at that point.  ``peel_walrus_binds`` gives a
    # held bind the value of the latest earlier bind of the same name in the
    # same evaluation; with none, it keeps the read of the name from before
    # the expression (``IfExpSugar._holding``).
    held: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "presented_value", self.assigned_value)

    @classmethod
    def carrying(
        cls,
        name: str,
        assigned_value: FloorValue,
        presented_value: FloorValue,
        evaluation: str | None = None,
        held: bool = False,
    ) -> "NamedExpressionValue":
        carried = cls(name, assigned_value, evaluation=evaluation, held=held)
        object.__setattr__(carried, "presented_value", presented_value)
        return carried

    def extend_scope(self, ctx):
        binds, presented = peel_walrus_binds(self)
        return presented.extend_scope(bind_walrus_binds(binds, ctx))

    def bind(self, ctx):
        """``ctx`` with this walrus's bind: the assigned value under the
        evaluation key, never under the name.  Every read of the name after
        the walrus is a reference to the key (``NamedExpr.substitution_binding``;
        anything evaluated after the walrus in its statement,
        ``nodes._scope_after``).
        The one place a walrus writes the temporal; ``extend_scope`` and every
        carrier (``bind_walrus_binds``) apply it.  A walrus substitution never
        keyed has no read that refers to it (its reads were given its value),
        and writes nothing."""
        # Root mint is Floor-owned when the reducer has no ambient context yet
        # (function desugar(None) / SourceFile production tooth).
        if ctx is None:
            from sugar_lift_py_tests.context import ReduceContext

            ctx = ReduceContext.root(owner="NamedExpressionValue")
        written = self.written()
        if written is None:
            return ctx
        key, _value = written
        if ctx.temporal.value_if_bound(key) == self.assigned_value:
            # This evaluation's bind is already in the temporal: a later read
            # of a value that carries it (a name substitution inlined the
            # walrus's right-hand side, an assignment's record answered it) is
            # not the walrus evaluating again, and binding the key again would
            # shadow a write of the name made since (a reference reads the
            # later of the two, ``EvaluationRefSugar``).
            return ctx
        return replace(ctx, temporal=ctx.temporal.bind_value(key, self.assigned_value))

    def written(self):
        """``(key, value)``: the assigned value under this evaluation's key,
        qualified by the reduction running now (``evaluation_here``: in a live
        loop each item's evaluation is its own key), or None for a walrus
        never keyed.  What ``bind`` writes, and what a statement that runs
        the walrus where its bind would not reach the rest of the block
        publishes as it leaves (a live ``for``'s iterable,
        ``LoopRecurrenceSugar``)."""
        if self.evaluation is None:
            return None
        from sugar_lift_py_tests.sugar.evaluation_ref_sugar import evaluation_here

        return evaluation_here(self.evaluation), self.assigned_value

    def as_expression_statement(self):
        """A bare ``(name := value)`` statement still binds ``name`` afterward."""
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.completed(self)

    def contribution(self):
        return self.presented_value.contribution()

    def follow_rest(self):
        return self.presented_value.follow_rest()

    def inv_contribution(self):
        return self.presented_value.inv_contribution()

    def post_contribution(self):
        return self.presented_value.post_contribution()

    def to_term(self, *, owner: str):
        return self.presented_value.to_term(owner=owner)

    def callsites(self):
        return self.presented_value.callsites()

    def truth(self, site):
        return self.presented_value.truth(site).and_then(self._carry)

    def negate(self):
        return self.presented_value.negate().and_then(self._carry)

    # --- left-hand: presented floor owns the comparison ---

    def is_identical(self, other, site):
        return self.presented_value.is_identical(other, site).and_then(self._carry)

    def equals(self, other, site, ctx):
        return self.presented_value.equals(other, site, ctx).and_then(self._carry)

    def less_than(self, other, site, ctx):
        return self.presented_value.less_than(other, site, ctx).and_then(self._carry)

    def less_equal(self, other, site, ctx):
        return self.presented_value.less_equal(other, site, ctx).and_then(self._carry)

    def greater_than(self, other, site, ctx):
        return self.presented_value.greater_than(other, site, ctx).and_then(self._carry)

    def greater_equal(self, other, site, ctx):
        return self.presented_value.greater_equal(other, site, ctx).and_then(
            self._carry
        )

    # --- right-hand: operator-owned typed double-dispatch (no string door) ---

    def less_than_from_left(self, left, site, ctx):
        """``left < (n := e)`` — presented is the RHS; carry the walrus bind."""
        return left.less_than(self.presented_value, site, ctx).and_then(self._carry)

    def less_equal_from_left(self, left, site, ctx):
        """``left <= (n := e)`` — typed RHS door; not string-admitted."""
        return left.less_equal(self.presented_value, site, ctx).and_then(self._carry)

    def greater_than_from_left(self, left, site, ctx):
        """``left > (n := e)`` — typed RHS door; not string-admitted."""
        return left.greater_than(self.presented_value, site, ctx).and_then(self._carry)

    def greater_equal_from_left(self, left, site, ctx):
        """``left >= (n := e)`` — typed RHS door; not string-admitted."""
        return left.greater_equal(self.presented_value, site, ctx).and_then(self._carry)

    def equals_from_left(self, left, site, ctx):
        """``left == (n := e)`` — typed RHS door; not string-admitted."""
        return left.equals(self.presented_value, site, ctx).and_then(self._carry)

    def is_identical_from_left(self, left, site):
        """``left is (n := e)`` — typed RHS door; not string-admitted."""
        return left.is_identical(self.presented_value, site).and_then(self._carry)

    def subscript(self, index, site):
        # The presented value is read through the one subscript door
        # (``discharge_subscript``): a parameter in either operand defers to
        # the caller, and the walrus bind rides the deferred read.
        from sugar_lift_py_tests.operations.subscript_operation import (
            discharge_subscript,
        )

        return discharge_subscript(
            self.presented_value,
            index,
            site,
            None,
            owner="NamedExpressionValue.subscript",
        ).and_then(self._carry)

    def setitem(self, index, value, site, ctx):
        return self.presented_value.setitem(index, value, site, ctx).and_then(
            self._carry
        )

    def delitem(self, index, site, ctx):
        return self.presented_value.delitem(index, site, ctx).and_then(self._carry)

    def attribute(self, name, site, ctx):
        return self.presented_value.attribute(name, site, ctx).and_then(self._carry)

    def _carry(self, presented: FloorValue):
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.completed(carry_walrus_binds((self,), presented))


# A walrus nested in a larger expression (``y = (x := 5)``, ``f((x := 5))``,
# ``[(x := 5)]``, ``(x := 5) + 1``, a comprehension's element) completes inside
# an operand.  Its bind reaches the enclosing statement's temporal by riding the
# value: every operand consumer hands its operands to ``consume_operands``,
# which peels the binds off them (``peel_walrus_binds``), runs the consumer on
# the values they present, and carries the binds onto each completed result
# (``carry_walrus_binds``); the statement applies them to its temporal
# (``bind_walrus_binds``).  A later operand of the same expression reduces
# in the context the earlier ones leave (``written_by``, ``reduce_operands``).
# A read after the walrus is an ``EvaluationRef`` to the walrus's key and
# resolves through it, never by evaluating the walrus's value again (temporal
# choice 1, #7661).


def peel_walrus_binds(value) -> tuple[tuple["NamedExpressionValue", ...], object]:
    """The walrus binds ``value`` carries, in evaluation order, and the value
    it presents beneath them.  An ordinary value carries none and presents
    itself.

    A held bind (a walrus that did not run on this arm) takes the value of
    the latest earlier bind of its name: in ``f((x := 1), 2 if c else (x :=
    3))`` the arm where ``c`` held leaves ``x`` at 1, not at what it was
    before the statement.  Peeling a longer chain sees every earlier bind, so
    the statement, which peels the whole chain, applies the resolved value."""
    binds = []
    while isinstance(value, NamedExpressionValue):
        bind = value
        if value.held:
            earlier = next(
                (prior for prior in reversed(binds) if prior.name == value.name),
                None,
            )
            if earlier is not None:
                bind = NamedExpressionValue(
                    value.name,
                    earlier.assigned_value,
                    evaluation=value.evaluation,
                    held=True,
                )
        binds.append(bind)
        value = value.presented_value
    return tuple(binds), value


def carry_walrus_binds(binds, presented):
    """``presented`` carrying ``binds`` (``peel_walrus_binds`` order), each
    bind as the kind of write it is (a walrus's, or a callee's store,
    ``CallerStoreValue``)."""
    for bind in reversed(binds):
        presented = type(bind).carrying(
            bind.name, bind.assigned_value, presented, bind.evaluation, bind.held
        )
    return presented


@dataclass(frozen=True)
class CallerStoreValue(NamedExpressionValue):
    """A store a callee made on an object its caller sees
    (``call_site_value.caller_visible_stores``), riding the call's completed
    value to the caller's statement as a walrus's write rides its value: through
    every operand door (``consume_operands``), applied where the statement
    applies its writes (``bind_walrus_binds``).  So the caller sees what the
    callee did wherever the call sits -- a statement alone, an assignment's
    value, an argument, a condition -- as a halt leaving the call carries it
    in its record (``call_site_value.at_the_call``).

    ``assigned_value`` is the store (a ``ReceiverFieldStoreValue``); it binds
    no name and no key."""

    def bind(self, ctx):
        if ctx is None:
            from sugar_lift_py_tests.context import ReduceContext

            ctx = ReduceContext.root(owner="CallerStoreValue")
        return self.assigned_value.extend_scope(ctx)

    def written(self):
        return None


def carry_caller_stores(stores, presented):
    """``presented`` carrying each callee store in ``stores``
    (``CallerStoreValue``), in the order the callee made them."""
    return carry_walrus_binds(
        tuple(CallerStoreValue("", store) for store in stores), presented
    )


def caller_stores_of(binds):
    """``(walrus_binds, stores)``: ``binds`` (``peel_walrus_binds``) parted
    into a walrus's writes and the callee stores among them
    (``CallerStoreValue``), each kept in order."""
    walrus = tuple(bind for bind in binds if not isinstance(bind, CallerStoreValue))
    stores = tuple(
        bind.assigned_value for bind in binds if isinstance(bind, CallerStoreValue)
    )
    return walrus, stores


def bind_walrus_binds(binds, ctx):
    """``ctx`` with each walrus bind applied in evaluation order (the same
    ``ctx`` object when there is none)."""
    for bind in binds:
        ctx = bind.bind(ctx)
    return ctx


def written_by(operand, ctx):
    """``ctx`` with the walrus writes ``operand`` (an evaluated operand)
    carries applied (``bind_walrus_binds``): the context an operand evaluated
    after it is evaluated in.

    Python evaluates operands left to right and a walrus writes when it
    completes, so an operand after it reads its write: in ``(y := f(x)) and
    y > 0`` the right operand's ``y`` is the walrus's value.  A consumer that
    evaluates one operand after another (``BinOpSugar``, ``BoolOpSugar``, a
    comparison, ``ChainedCompareSugar``, ``IfExpSugar``'s arms after its test,
    a call's later actuals and the call itself, a subscript's index after its
    receiver, an f-string's later parts, a live ``for``'s items after its
    iterable, and every fold of ``reduce_operands``: a display's elements, a
    slice's bounds, a container call's arguments) hands the later one this
    context, and the earlier one to the one operand
    door (``consume_operands``) as before.  A read after a walrus in its
    statement is a reference to the walrus's key (``nodes._scope_after``);
    inside a comprehension only this bind holds that key in the member
    (``ComprehensionSugar._written``): where no consumer evaluated the read
    in this context, the read is refused by name.  ``ctx`` itself when the
    operand carries no write or ``ctx`` is a context that holds no temporal;
    with no context at all, the writes are bound on a root one
    (``NamedExpressionValue.bind``)."""
    binds, _presented = peel_walrus_binds(operand)
    if not binds or (ctx is not None and not hasattr(ctx, "temporal")):
        return ctx
    return bind_walrus_binds(binds, ctx)


def reduce_operands(operands, ctx, *, factored: bool = False):
    """``operands`` (sugars) reduced left to right, each in the context the
    ones before it leave (``written_by`` of each in turn), completed as the
    tuple of their values: ``[(b := 2), b]`` reads ``b`` as 2.  Each value
    still carries its own binds, for ``consume_operands`` to carry onto the
    consumer's result.

    The one left-to-right operand fold: a display's elements, a slice's
    bounds, a container call's arguments.  An omitted operand (``None``: a
    slice's absent bound) presents ``None`` and carries nothing.  An operand
    is reduced only on a completed arm of the ones before it: one that halts
    leaves the later ones unevaluated, as Python does.  ``factored``: each
    operand presents at most one completed arm (``factored_operand``, #6324),
    for a fold whose accumulator would otherwise multiply by every
    partitioning operand."""
    from sugar_lift_py_tests.outcome import ExitSet
    from sugar_lift_py_tests.outcome.exit_set import factored_operand

    def reduce_next(collected, operand):
        if operand is None:
            return ExitSet.completed((*collected, None))
        operand_ctx = ctx
        for earlier in collected:
            operand_ctx = written_by(earlier, operand_ctx)
        outcome = operand.desugar(operand_ctx)
        if factored:
            outcome = factored_operand(outcome)
        return outcome.and_then(
            lambda value: ExitSet.completed((*collected, value))
        )

    outcome = ExitSet.completed(())
    for operand in operands:
        outcome = outcome.and_then(
            lambda collected, operand=operand: reduce_next(collected, operand)
        )
    return outcome


def consume_operands(step, *operands):
    """``step`` applied to the values ``operands`` present, each completed
    result carrying every walrus bind the operands carry, in evaluation order.

    The one operand door.  An expression that consumes evaluated operands (a
    call's actuals, an arithmetic or comparison operand, a display's elements,
    a subscript, a short-circuit operand, an f-string part, a conditional
    expression's test, a container mutation's arguments) runs its step here,
    so a walrus in an operand is evaluated once and its bind still reaches the
    enclosing statement.  The bind rides only the arms the step completed
    under after the operand ran: a short-circuit's later operand is consumed
    inside its continuing face, so its bind never reaches the stopping face.
    A halted arm leaves the statement and carries nothing.  With no bind
    among the operands this is ``step(*operands)`` exactly.

    The operands were reduced left to right, each under the state after the
    ones before it (``written_by``, ``reduce_operands``): a later
    operand's read of an earlier operand's walrus reads its key."""
    binds: tuple = ()
    presented = []
    for operand in operands:
        carried, value = peel_walrus_binds(operand)
        binds += carried
        presented.append(value)
    outcome = step(*presented)
    if not binds:
        return outcome
    from sugar_lift_py_tests.outcome import ExitSet

    return outcome.and_then(
        lambda result: ExitSet.completed(carry_walrus_binds(binds, result))
    )
