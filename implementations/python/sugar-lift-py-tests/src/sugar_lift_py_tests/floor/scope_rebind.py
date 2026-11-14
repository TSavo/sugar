from __future__ import annotations

from dataclasses import dataclass, replace

from .floor_value import FloorValue


def _context_for_rebind(ctx, *, owner: str):
    """Scope-mutating Floors mint a root when the reducer has no context yet."""
    if ctx is not None:
        return ctx
    from sugar_lift_py_tests.context import ReduceContext

    return ReduceContext.root(owner=owner)


@dataclass(frozen=True)
class ScopeRebind(FloorValue):
    """A mutation rebinds to the UPDATED VALUE; the history is in the value's nested
    term, not in a recomposable source: a let that holds the folded result, not a
    recoverable source body."""

    name: str
    value: FloorValue

    def contribution(self):
        # A rebind is support: present, threaded into scope, contributes nothing to
        # the block record.
        return ()

    def extend_scope(self, ctx):
        # Thread the updated value forward so later statements resolve the name.
        # Root mint is Floor-owned when the reducer has no ambient context yet.
        ctx = _context_for_rebind(ctx, owner="ScopeRebind")
        return replace(ctx, temporal=ctx.temporal.bind_value(self.name, self.value))

    def as_expression_statement(self):
        # The rebind IS the statement outcome -- scope rides; contribution is empty.
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.completed(self)

    def to_term(self, *, owner: str):
        # Rebind holds the folded result; project that value's nested term.
        # Missing projection stays a loud Floor/Projection gap on unhandled floors
        # (via FloorValue.to_term) — never a soft RuntimeEffect.
        return self.value.to_term(owner=owner)

    def guarded(self, formula):
        return GuardedScopeRebind((formula,), self.name, self.value)


@dataclass(frozen=True)
class ScopeRebinds(FloorValue):
    """Carry several exact callback mutations back into the caller scope."""

    bindings: tuple[tuple[str, FloorValue], ...]

    def contribution(self):
        return ()

    def extend_scope(self, ctx):
        ctx = _context_for_rebind(ctx, owner="ScopeRebinds")
        temporal = ctx.temporal
        for name, value in self.bindings:
            temporal = temporal.bind_value(name, value)
        return replace(ctx, temporal=temporal)

    def as_expression_statement(self):
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.completed(self)


def bind_unpack_projections(value, evaluation: str | None):
    """An unpack's completed answer, each target's member bound under its
    projection of the statement's one evaluation instead of its name.

    Temporal choice 1 (#7661): a later read of ``a`` after ``a, b = f()`` is
    an ``EvaluationRef`` to ``a``'s projection of the statement's evaluation,
    never the name looked up by spelling, so the name is not written: the
    projection is the one binding a read reaches (a live loop's latch reads
    it as ``a``'s write: ``live_loop_construction._carried_writes``). Without
    an evaluation key (a statement that was never substituted) the answer is
    unchanged: the names alone.
    """
    from sugar_lift_py_tests.outcome import ExitSet

    if evaluation is None or not isinstance(value, ScopeRebinds):
        return ExitSet.completed(value)
    from sugar_lift_py_tests.sugar.evaluation_ref_sugar import evaluation_here
    from sugar_lift_py_tests.temporal.temporal_context import projection_key

    # In a live loop each item's evaluation is its own key.
    projected = tuple(
        (evaluation_here(projection_key(evaluation, n)), m)
        for n, m in value.bindings
    )
    return ExitSet.completed(ScopeRebinds(projected))


@dataclass(frozen=True)
class GuardedScopeRebind(FloorValue):
    """A branch-local rebind carried in the record under one or more guards.

    It deliberately does not extend temporal scope. What a name binds to after a
    branch is the phi substitution builds (``If.substitute``), which joins only
    names bound in both faces. Keeping this marker non-binding preserves the
    one-arm NameError path.
    """

    guards: tuple
    name: str
    value: FloorValue

    def contribution(self):
        return ()

    def guarded(self, formula):
        return GuardedScopeRebind((formula, *self.guards), self.name, self.value)
