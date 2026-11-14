"""An assignment evaluates its RHS at the statement; later reads see its value.

Substitution threads ``x = <rhs>`` by inlining the RHS sugar at every later
read of ``x``. Python does not: it evaluates the RHS once, at the assignment
statement, inside whatever ``try``/``with`` encloses it and in statement order.
So ``try: x = textwrap.dedent('a') except ValueError: x = 'h'; return x`` may
take the handler, and ``x = may_raise(); return 3`` may raise even though
``x`` is never read.

The law has two halves, and this module owns both:

- **The statement evaluates.** ``evaluate_assignment_values`` desugars each RHS
  at the assignment, in Python's evaluation order. Its halt faces leave HERE,
  as the statement's own exits; only its completed faces continue, each with
  ``ctx.assigned_values`` extended by ``(rhs key, completed value)``.
- **A read never re-evaluates.** ``Sugar.desugar`` of a sugar whose key is
  recorded answers ``ExitSet.completed(<completed value>)``: the value from the
  face the statement completed under, never a second evaluation that could
  raise again. The completed face's guard already rides the path that reaches
  the read, so each effect is counted once.

A RHS that reduces to one plain completed arm (unguarded, no faces, owing
nothing) cannot halt; its reads keep the substitution they always had
(re-reducing a total RHS denotes the same value).
"""

from __future__ import annotations

_MISS = object()


def assigned_key(sugar) -> object | None:
    """The occurrence key of one RHS sugar: its type and source fragment.

    Substitution shares the RHS node, but a read may sit in a different
    construction coordinate and so hold a different sugar object for it; the
    occurrence (type + exact fragment) is what both name. A sugar without a
    source fragment has no occurrence to key and is never recorded; the
    statement's own targets still receive its one completed value directly.
    """
    site = getattr(sugar, "site", None)
    if site is None or not hasattr(site, "span") or not hasattr(site, "unit"):
        return None
    try:
        hash(site)
    except TypeError:
        return None
    # A shadow evaluation minted once per substitution (an unrolled
    # iteration's mutating call) shares its span with every other iteration's;
    # its evaluation coordinate (span plus occurrence tags, never a process
    # draw) is what tells their evaluations apart.
    token = getattr(sugar, "evaluation_token", None)
    if token is not None:
        return (type(sugar), site, token)
    return (type(sugar), site)


def recorded_value(ctx, sugar):
    """The completed value an earlier assignment recorded for ``sugar``, or _MISS."""
    rows = getattr(ctx, "assigned_values", None)
    if not rows:
        return _MISS
    key = assigned_key(sugar)
    if key is None:
        return _MISS
    for candidate, value in reversed(rows):
        if candidate == key:
            return value
    return _MISS


def _bind_names(active, bind, completed):
    """Rebind each live-loop ``(name, value index)`` to its completed value in
    the temporal, as ``AugAssignSugar`` always has: a live loop body is read
    through the temporal, not substituted per item, so the next statement and
    the next item see the assignment."""
    from sugar_lift_py_tests.floor.floor_value import FloorValue
    from sugar_lift_py_tests.floor.scope_rebind import ScopeRebind

    live = getattr(active, "live_loop_names", frozenset())
    for name, index in bind:
        value = completed[index]
        if name not in live or not isinstance(value, FloorValue):
            continue
        active = ScopeRebind(name, value).extend_scope(active)
    return active


def evaluate_assignment_values(values, ctx, tail=None, bind=()):
    """Evaluate ``values`` (RHS sugars, in evaluation order) at the statement.

    Returns the statement's outcome: every halt face of every RHS, in order
    (a later RHS never runs on an earlier one's halt), and one completed
    ``_ReducedBlock`` per completed path whose context records each RHS's
    completed value. ``tail(ctx, completed)``, if given, runs after the last
    RHS (store targets) with ``completed`` the completed value of each RHS, in
    ``values`` order, so a target consumes the one evaluation instead of a
    second; its outcome replaces the empty completed block. ``bind`` (without
    ``tail``) names ``(name, value index)`` pairs the completed path rebinds in
    the temporal.
    """
    from sugar_lift_py_tests.context import ReduceContext
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.outcome import ExitSet
    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        _ReducedBlock,
        plain_completed_value,
    )

    if ctx is None:
        ctx = ReduceContext.root(owner="evaluate_assignment_values")

    def finish(active, completed):
        if tail is not None:
            return tail(active, completed)
        if bind:
            bound = _bind_names(active, bind, completed)
            if bound is not active:
                return ExitSet.completed(_ReducedBlock((), True, (), (), bound))
        if active is ctx:
            # Nothing recorded: the statement contributes nothing, as before.
            return ExitSet.completed(BlockValue((), can_fall_through=True))
        return ExitSet.completed(_ReducedBlock((), True, (), (), active))

    def step(index, active, completed=()):
        if index == len(values):
            return finish(active, completed)
        sugar = values[index]
        key = assigned_key(sugar)
        # The statement's own evaluation is never answered from the record:
        # a loop re-reducing this statement evaluates its RHS again.
        own_ctx = active if key is None else active.without_assigned_value(key)
        outcome = sugar.desugar(own_ctx)
        if isinstance(outcome, ExitSet) and outcome.halts() == outcome.exits:
            # Every arm halts: no later RHS or target runs.
            return outcome
        plain = plain_completed_value(outcome)
        if plain is not None:
            follow = plain.follow_rest()
            if not follow.continues:
                # A value whose rest does not run: the statement halts here
                # and no later RHS or target runs. It is handed back as-is so
                # the enclosing block routes it.
                return outcome
            evaluated = _walrus_bound(active, plain)
            if key is not None and _binds_live_name(active, bind, index):
                # A live loop body rebinds names this RHS may read: a later
                # read of this RHS must see this evaluation, not re-reduce
                # over the rebound temporal.
                return step(
                    index + 1,
                    evaluated.with_assigned_value(key, plain),
                    (*completed, plain),
                )
            return step(index + 1, evaluated, (*completed, plain))
        if key is None:
            # No occurrence to record: the statement still halts here, and a
            # read keeps substitution (it was never answered from a record).
            return outcome.and_then(
                lambda value: step(
                    index + 1, _walrus_bound(active, value), (*completed, value)
                )
            )
        return outcome.and_then(
            lambda value: step(
                index + 1,
                _walrus_bound(active, value).with_assigned_value(key, value),
                (*completed, value),
            )
        )

    return step(0, ctx)


def _walrus_bound(active, value):
    """``active`` with the binds of every walrus the completed RHS ``value``
    carries (``y = (x := 5)``, ``y = f((x := 5))``): the walrus completed
    inside the RHS, at this statement, so the rest of the block reads ``x``
    through its key.  ``active`` itself when the RHS carries none."""
    from sugar_lift_py_tests.floor.named_expression_value import (
        bind_walrus_binds,
        peel_walrus_binds,
    )

    binds, _presented = peel_walrus_binds(value)
    return bind_walrus_binds(binds, active)


def _binds_live_name(ctx, bind, index) -> bool:
    """Inside a live loop body every assignment's RHS is recorded: a later
    statement reads it through substitution, and the temporal it was reduced
    over may since have been rebound."""
    del bind, index
    return bool(getattr(ctx, "live_loop_names", frozenset()))
