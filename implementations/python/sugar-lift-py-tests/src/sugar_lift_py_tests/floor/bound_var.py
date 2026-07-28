from __future__ import annotations

from dataclasses import dataclass, field, replace

from .floor_value import FloorValue

_UNSET_OUTCOME = object()


@dataclass(frozen=True)
class BoundVar(FloorValue):
    """A bound variable: a name ALIASING an expression.

    `let x = y()` binds x to the SOURCE `y()` (a composed body), not to y()'s
    collapsed value -- so y() stays recoverable. A reference to x recomposes the
    source: x genuinely IS y(), reached through the alias x. A later pass recovers the
    original expression from `.source` -- the map element under a lambda param, the
    curried argument, the definition a temporal rewrite has to hoist. Collapsing the
    binding to a value (the old BindingValue) made all of that impossible: once `y()`
    is a number you cannot get `y()` back.

    The block threads a BoundVar as a scope effect (a let); it is not itself a return.
    """

    name: str
    source: object  # the rhs sugar: recoverable + recomposable; answers .desugar
    # The DEFINITION scope -- the ctx as it stood when this binding was made, where the
    # name still holds its OLD value. A reference recomposes `source` against THIS, not
    # the current scope, so a self-referential rebind (`x = x + 1`) reads the old x and
    # terminates instead of recomposing against itself forever.
    scope: object = None
    # A definition-scoped alias has one semantic answer. Keep the source and scope
    # intact for temporal rewrites, while retaining the exact Outcome produced by
    # their first composition. Unscoped aliases remain context-dependent and are
    # deliberately never cached.
    _cached_outcome: object = field(
        default=_UNSET_OUTCOME, init=False, compare=False, repr=False
    )

    def contribution(self):
        # A let is support: present, threaded into scope, contributes nothing to the
        # block record.
        return ()

    def extend_scope(self, ctx):
        # Thread this binding forward so later statements resolve the name.
        from sugar_lift_py_tests.sugar.nonlocal_sugar import (
            reject_unconstructed_nonlocal_store,
        )

        reject_unconstructed_nonlocal_store(ctx, self.name)
        return replace(ctx, temporal=ctx.temporal.bind_value(self.name, self))

    def answer(self, ctx=None):
        # A context-dependent alias has no stable definition key, so recompute it
        # against each caller rather than leaking one caller's answer into another.
        if self.scope is None:
            return self.source.desugar(ctx)

        # A definition-scoped alias is semantically fixed. Reduce its recoverable
        # source once against the captured old scope, then replay that same Outcome.
        outcome = self._cached_outcome
        if outcome is _UNSET_OUTCOME:
            outcome = self.source.desugar(self.scope)
            object.__setattr__(self, "_cached_outcome", outcome)
        return outcome

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.gap.panic import construction_panic_gap
        from sugar_lift_py_tests.gap.info import GapKind, GapLocus
        from sugar_lift_py_tests.outcome import Incomplete, complete_value

        outcome = self.answer(self.scope)
        if isinstance(outcome, Incomplete):
            # The source lawfully remains a typed Incomplete at its producer.
            # Collapsing that incomplete effect into a completed term is a missing
            # Floor recognizer: structured ConstructionPanic, never bare RuntimeError.
            # Same law as FloorValue.to_term: the owner is THIS projection, not
            # the requester. ``owner`` arrives as the caller's ``str(site)``
            # fragment repr, so it joins the bound name in blame.
            construction_panic_gap(
                owner="BoundVar.to_term",
                blame=f"{self.name} requested-by={owner}",
                observed=type(outcome.effect).__name__,
                requested="completed BoundVar term substitution",
                fix=(
                    "construct the bound source's runtime-dependent result before "
                    "projecting BoundVar to a term; never read an incomplete effect "
                    f"as a completed call argument ({outcome.reason})"
                ),
                gap_kind=GapKind.FLOOR,
                gap_locus=GapLocus.PROJECTION,
            )
        value = complete_value(outcome, owner=f"{owner} bound source")
        return value.to_term(owner=owner)

    def add(self, other, site):
        return self.answer(self.scope).and_then(lambda value: value.add(other, site))
