"""An assignment evaluates its RHS at the statement; later reads see its value.

Python evaluates the RHS once, at the assignment statement, inside whatever
``try``/``with`` encloses it and in statement order. So ``try: x =
textwrap.dedent('a') except ValueError: x = 'h'; return x`` may take the
handler, and ``x = may_raise(); return 3`` may raise even though ``x`` is never
read.

The law has two halves, and this module owns both:

- **The statement evaluates.** ``evaluate_assignment_values`` desugars each RHS
  at the assignment, in Python's evaluation order. Its halt faces leave HERE,
  as the statement's own exits; only its completed faces continue, each with
  the value bound under each Name target's key (``evaluations``,
  ``Assign.target_evaluations``) and ``ctx.assigned_values`` extended by
  ``(rhs key, completed value)``.
- **A read never re-evaluates.** Substitution rewrites every later read of a
  Name target to a reference to its key (``EvaluationRefSugar``): the value
  the statement completed with, never the RHS inlined at the read and
  evaluated again against whatever was rebound since.  A call's result kept
  as its object identity (``Assign.refine_binding_entries``,
  ``OpaqueObjectStateV1``, ``ObjectPlaceStateV1``) reads the same key; a
  stored field or a container's contents after a store read the store's key
  (``place``), and an object after its field stores is that key with each
  store's key read folded over it.  A path's root after a path mutation is
  read through the name's key, never the display it was given.  A
  read of a RHS sugar that is still inlined answers
  ``ExitSet.completed(<completed value>)`` from the record when it is
  recorded: the value from the face the statement completed under, never a
  second evaluation that could raise again.

A RHS that reduces to one plain completed arm (unguarded, no faces, owing
nothing) cannot halt and is recorded only inside a live loop body; outside one
an inlined read of it is reduced again.
"""

from __future__ import annotations

import functools

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
    # A source fragment is hashable; an unhashable site is a lifter bug, and
    # its TypeError propagates here rather than answering "no key".
    hash(site)
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


def carried_write_key(site, name: str) -> str:
    """The key an assignment statement at ``site`` binds the value it writes
    to ``name`` under, where ``name`` is a name a live loop carries.

    A write of a carried name is read by the loop, never by spelling: the
    recurrence hands on (and publishes) the latest of every write of the name
    and its header (``LoopRecurrenceSugar._latest_written``), and
    ``construct_live_loop_recurrence`` names this same key from the
    statement node (``live_loop_construction._carried_writes``).  The key is
    an evaluation key (``EVALUATION_PREFIX``), so it is never a source name,
    an ``if`` carries it out of an arm, and each live item qualifies it as its
    own (``evaluation_here``)."""
    return _carried_write_key(site.seal().cid, name)


@functools.lru_cache(maxsize=65536)
def _carried_write_key(statement_fragment_cid: str, name: str) -> str:
    from sugar_lift_python_source.canonical import cid_of_json
    from sugar_lift_py_tests.temporal.temporal_context import EVALUATION_PREFIX

    return EVALUATION_PREFIX + cid_of_json(
        {
            "kind": "python-carried-name-write-v1",
            "statementFragmentCid": statement_fragment_cid,
            "name": name,
        }
    )


def _bind_carried_writes(active, bind, completed, site):
    """``active`` with each ``(name, value index)`` a live loop carries bound
    to its completed value under this statement's write of the name
    (``carried_write_key``), qualified by the live loop item it runs in
    (``evaluation_here``).  The name is never written: every later read of it
    in the block is substituted, and the loop reads the write by its key."""
    from sugar_lift_py_tests.floor.floor_value import FloorValue
    from sugar_lift_py_tests.floor.scope_rebind import ScopeRebind
    from sugar_lift_py_tests.sugar.evaluation_ref_sugar import evaluation_here

    live = getattr(active, "live_loop_names", frozenset())
    for name, index in bind:
        value = completed[index]
        if name not in live or not isinstance(value, FloorValue):
            continue
        if not hasattr(site, "seal"):
            from sugar_lift_py_tests.gap.panic import construction_panic_gap

            construction_panic_gap(
                owner="assigned_value._bind_carried_writes",
                blame=site,
                observed=(
                    f"assignment of `{name}`, a name a live loop carries, "
                    "with no source fragment to key its write"
                ),
                requested="the assignment statement's source fragment",
                fix="construct the assignment sugar with its statement fragment",
            )
        key = evaluation_here(carried_write_key(site, name))
        active = ScopeRebind(key, value).extend_scope(active)
    return active


def _bind_evaluations(active, evaluations, index, value):
    """``active`` with RHS ``index``'s completed ``value`` bound under the key
    of each Name target it is assigned to (``evaluations``: ``(key, value
    index)``, ``Assign.target_evaluations``), qualified by the live loop item
    it runs in (``evaluation_here``).  After ``y = e`` every later read of
    ``y`` is a reference to that key: the value ``e`` had here, never ``e``
    evaluated again after a rebind.  Bound as soon as the RHS completes, as a
    walrus inside it is (``_walrus_bound``), so a class body's later field
    reads it too; no RHS of the same statement reads it (substitution threads
    the binding to the statements after this one)."""
    from sugar_lift_py_tests.floor.floor_value import FloorValue
    from sugar_lift_py_tests.floor.scope_rebind import ScopeRebind
    from sugar_lift_py_tests.sugar.evaluation_ref_sugar import evaluation_here

    if not isinstance(value, FloorValue):
        return active
    for key, at in evaluations:
        if at == index:
            active = ScopeRebind(evaluation_here(key), value).extend_scope(active)
    return active


def evaluate_assignment_values(
    values, ctx, tail=None, bind=(), evaluations=(), site=None
):
    """Evaluate ``values`` (RHS sugars, in evaluation order) at the statement.

    Returns the statement's outcome: every halt face of every RHS, in order
    (a later RHS never runs on an earlier one's halt), and one completed
    ``_ReducedBlock`` per completed path whose context records each RHS's
    completed value. ``tail(ctx, completed)``, if given, runs after the last
    RHS (store targets) with ``completed`` the completed value of each RHS, in
    ``values`` order, so a target consumes the one evaluation instead of a
    second; its outcome replaces the empty completed block. ``bind`` (without
    ``tail``) names the ``(name, value index)`` pairs the statement (at
    ``site``) assigns: the completed path binds each name a live loop carries
    under the statement's write of it (``_bind_carried_writes``).
    ``evaluations`` names ``(key, value index)`` pairs: each
    RHS's completed value is bound under a Name target's key as soon as it
    completes (``_bind_evaluations``), so the completed path and ``tail``
    carry it.
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
            bound = _bind_carried_writes(active, bind, completed, site)
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
            evaluated, plain = _walrus_bound(active, plain)
            evaluated = _bind_evaluations(evaluated, evaluations, index, plain)
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
        def completed_face(value):
            evaluated, value = _walrus_bound(active, value)
            evaluated = _bind_evaluations(evaluated, evaluations, index, value)
            if key is not None:
                evaluated = evaluated.with_assigned_value(key, value)
            return step(index + 1, evaluated, (*completed, value))

        # With no occurrence to record (``key is None``) the statement still
        # halts here, and a read keeps substitution (it was never answered
        # from a record).
        return outcome.and_then(completed_face)

    return step(0, ctx)


def _walrus_bound(active, value):
    """``(active, value)`` with the binds of every walrus the completed RHS
    ``value`` carries applied to ``active`` (``y = (x := 5)``,
    ``y = f((x := 5))``, ``xs.append((x := 5))``), and the value the RHS
    presents beneath them: the walrus completed inside the RHS, at this
    statement, so the rest of the block reads ``x`` through its key, and the
    targets, the record and ``tail`` hold the value itself.  ``active`` and
    ``value`` themselves when the RHS carries none."""
    from sugar_lift_py_tests.floor.named_expression_value import (
        bind_walrus_binds,
        peel_walrus_binds,
    )

    binds, presented = peel_walrus_binds(value)
    return bind_walrus_binds(binds, active), presented


def _binds_live_name(ctx, bind, index) -> bool:
    """Inside a live loop body every assignment's RHS is recorded: a later
    statement reads it through substitution, and the temporal it was reduced
    over may since have been rebound."""
    del bind, index
    return bool(getattr(ctx, "live_loop_names", frozenset()))
