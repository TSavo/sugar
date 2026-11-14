"""`match subject: case P [if g]: body ...` -- structural pattern matching.

A match is sequential, first-case-wins: case i runs exactly when the subject
matches P_i, matched no earlier *selected* case, and its guard (if any) is true.

Subject evaluates ONCE. Pattern captures bind the subject for that case's
guard and body only:

  - tentative bind for guard evaluation
  - false guard rolls the tentative bind back before the next case
  - true guard commits the bind for the body under the selection formula
  - guard halt bypasses later cases under the matched-and-reached-guard path,
    carrying the halt's pre-effect state (Halted.state preserved)

ExitSet law (advisor #6716 rework):

  - every pattern / guard / body face is restricted by ``not_prev`` (or a
    tighter selection); later-case outcomes never fire unguarded
  - Halted faces keep ``effect`` and ``state``; guards compose via ExitSet.guarded
  - multi-face guard ExitSets are fanned per face (no completed[0] collapse)
  - equality testimony routes through Floor ``equals`` + ``predicate_formula``
    (value.truth), never nested getattr formula probes
  - a completed pattern / equality / guard face feeds the selection formula
    AND what it owes: every arm past it is sequenced after it (``_after``),
    so its ``owed`` reaches the case body's result and every later arm (#7757)

Value patterns and catch-all / bare capture are owned. Structural patterns
stay loud at the construction door (nodes.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import ExitSet, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_return_pair


@dataclass(frozen=True)
class MatchCaseSpec:
    """One case: value-pattern alternatives, optional guard, body, capture.

    ``alternatives`` is the tuple of literal sugars the subject may equal --
    ``(1,)`` for `case 1:`, ``(1, 2)`` for `case 1 | 2:`, and the EMPTY tuple
    for a catch-all (`case _:` or bare capture `case x:`, which always match).

    ``guard`` is the optional `if <expr>` sugar (None when absent).

    ``capture_name`` is the bare capture name for `case x:` / `case x if g:`;
    None for wildcards and pure value patterns. The capture is the subject
    FloorValue at this match -- not a free-name spelling lookup.
    """

    alternatives: tuple  # literal sugars; empty = catch-all / bare capture
    body: tuple
    guard: object | None = None  # Sugar | None
    capture_name: str | None = None


def _not_earlier(earlier: list):
    from sugar_lift_py_tests.ir import and_, not_
    from sugar_lift_py_tests.outcome.exit_set import true_guard

    if not earlier:
        return true_guard()
    parts = tuple(not_(f) for f in earlier)
    return and_(parts) if len(parts) > 1 else parts[0]


def _and_parts(*parts):
    from sugar_lift_py_tests.ir import and_
    from sugar_lift_py_tests.outcome.exit_set import true_guard

    flat = [p for p in parts if p is not None and p != true_guard()]
    if not flat:
        return true_guard()
    if len(flat) == 1:
        return flat[0]
    return and_(tuple(flat))


def _tentative_capture_ctx(ctx, capture_name: str | None, subject):
    """Bind capture_name → subject for this case only; caller discards after."""
    if capture_name is None:
        return ctx
    from sugar_lift_py_tests.context.reduce_context import ReduceContext
    from sugar_lift_py_tests.temporal.context_helpers import bind_temporal

    base = ctx if ctx is not None else ReduceContext.root(owner="MatchSugar.capture")
    return bind_temporal(
        base,
        capture_name,
        subject,
        owner="MatchSugar.tentative_capture",
        blame=f"match capture {capture_name!r}",
    )


def _after(guard, owed, exits):
    """``exits`` sequenced after the match step that reached them (#7757).

    The step is one completed arm under ``guard`` owing ``owed``: what the
    patterns, equalities and guards on the path into these arms incurred.
    ``ExitSet.sequence`` conjoins ``guard`` onto every arm and carries the
    debt onto every arm, completed and halted alike, so nothing a completed
    equality or guard face owed is dropped by being read as a formula only.
    Halted.state and partition faces ride through unchanged.
    """
    from sugar_lift_py_tests.outcome import Completed
    from sugar_lift_py_tests.outcome.exit_set import true_guard

    reached = true_guard() if guard is None else guard
    step = ExitSet((Completed(reached, None, owed=owed),))
    return step.sequence(lambda _reached: exits)


def _halted_face(face, prefix_guard):
    """Preserve a Halted face (effect + state) under an outer prefix."""
    from sugar_lift_py_tests.outcome.exit_set import ExitSet, Halted

    combined = _and_parts(prefix_guard, face.guard)
    return ExitSet(
        (
            Halted(
                combined,
                face.effect,
                face.state,
                face.faces,
                face.owed,
            ),
        )
    )


def _incomplete_as_halted(incomplete, prefix_guard):
    """A stateless halt under prefix: Halted with state=None is honest.

    No match path calls this since the match reads ``ExitSet`` arms only
    (#7825); ``test_halt_drops_7827`` pins that no path reaches it.
    """
    from sugar_lift_py_tests.outcome.exit_set import ExitSet

    return ExitSet.halted(incomplete.effect, prefix_guard, state=None)


def _formula_from_floor_value(value, site):
    """Equality / guard truth via Floor surface (value.truth), not getattr probes."""
    from sugar_lift_py_tests.sugar.if_sugar import predicate_formula

    return predicate_formula(value, site)


def _exceptional_faces_only(exits, prefix_guard):
    """Propagate only non-Completed control faces under ``prefix_guard``.

    Completed faces feed matching / guard truth; they must not also escape as
    completed Match outcomes by wholesale ExitSet union.
    """
    from sugar_lift_py_tests.outcome import Completed, Halted

    side = ExitSet(())
    for face in exits.exits:
        if isinstance(face, Completed):
            continue
        if isinstance(face, Halted):
            side = side.union(_halted_face(face, prefix_guard))
        else:
            raise NotImplementedError(
                f"match side face not lifted: {type(face).__name__}"
            )
    return side


def _pattern_match_formula_and_side_exits(subject, alternatives, site, not_prev, ctx):
    """Build match formula; exceptional alt/equality faces ride under not_prev.

    Returns ``(match_formula | None, side_exits: ExitSet, owed)``.
    Completed faces of alternative/equality ExitSets feed matching as
    formulas, and what they OWE is returned as ``owed`` for the caller to
    sequence onto every arm past this pattern (#7757). They are never
    unioned wholesale into the Match outcome. An equality halt is sequenced
    after the alternative that completed into it, so it owes what that
    alternative (and every alternative tried before it) owed.
    """
    from sugar_lift_py_tests.ir import or_
    from sugar_lift_py_tests.outcome import Completed
    from sugar_lift_py_tests.outcome.exit_set import owed_union, true_guard

    if not alternatives:
        return true_guard(), ExitSet(()), ()

    alts = []
    side = ExitSet(())
    owed: tuple = ()
    for alt in alternatives:
        alt_out = alt.desugar(ctx)
        if not isinstance(alt_out, ExitSet):
            raise NotImplementedError(
                f"match alternative outcome not lifted: {type(alt_out).__name__}"
            )
        # What the alternatives tried before this one incurred.
        before = owed
        # Exceptional/control faces only — not Completed outcomes.
        side = side.union(
            _after(None, before, _exceptional_faces_only(alt_out, not_prev))
        )
        for face in alt_out.exits:
            if not isinstance(face, Completed):
                continue
            # Matching under not_prev ∧ alt-face polarity (an unguarded face
            # adds nothing to either).
            eq_prefix = _and_parts(not_prev, face.guard)
            eq_out = subject.equals(face.value, site, ctx)
            eq_side, formula, eq_owed = _equality_outcome_under(
                eq_out, eq_prefix, site
            )
            side = side.union(_after(None, owed_union(before, face.owed), eq_side))
            owed = owed_union(owed, face.owed, eq_owed)
            if formula is not None:
                # When multi-face equality, formula is OR of (face.guard ∧ truth).
                alts.append(_and_parts(face.guard, formula))

    if not alts:
        return None, side, owed
    match_formula = or_(tuple(alts)) if len(alts) > 1 else alts[0]
    return match_formula, side, owed


def _equality_outcome_under(eq_out, not_prev, site):
    """Process subject.equals under not_prev; return (side, formula|None, owed).

    ExitSet Completed faces contribute ``face.guard ∧ truth(face.value)`` to
    the match formula, and their ``owed`` to the returned debt (#7757): the
    equality ran on every path past it, so the caller sequences that debt
    onto every such arm. Non-completed faces propagate separately (state and
    owed preserved). Never wholesale-unions Completed equality faces into side.
    """
    from sugar_lift_py_tests.ir import or_
    from sugar_lift_py_tests.outcome import Completed, Halted
    from sugar_lift_py_tests.outcome.exit_set import owed_union

    if not isinstance(eq_out, ExitSet):
        raise NotImplementedError(
            f"match equality outcome not lifted: {type(eq_out).__name__}"
        )
    side = ExitSet(())
    formulas = []
    owed: tuple = ()
    for face in eq_out.exits:
        if isinstance(face, Halted):
            side = side.union(_halted_face(face, not_prev))
            continue
        if isinstance(face, Completed):
            truth = _formula_from_floor_value(face.value, site)
            formulas.append(_and_parts(face.guard, truth))
            owed = owed_union(owed, face.owed)
            continue
        raise NotImplementedError(
            f"match equality face not lifted: {type(face).__name__}"
        )
    if not formulas:
        return side, None, owed
    formula = or_(tuple(formulas)) if len(formulas) > 1 else formulas[0]
    return side, formula, owed


def _guard_faces_under(guard_out, reached, site, body, body_ctx, match_formula, owed):
    """Fan a guard outcome into ExitSets under ``reached``.

    Returns ``(parts, earlier_bits, guard_owed)``.

    ``owed`` is what the path into this guard incurred (patterns and
    equalities of this and every earlier case); every part owes it.
    Per Completed face: body sequenced under ``reached ∧ face.guard ∧ truth``,
    owing ``owed`` and what the face owes. Per Halted face: preserve Halted
    under ``reached ∧ face.guard``; mark only ``match_formula ∧ face.guard``
    consumed (not the whole match path). ``guard_owed`` is every completed
    face's debt, which the paths past a false guard carry too (#7757).
    """
    from sugar_lift_py_tests.outcome import Completed, Halted
    from sugar_lift_py_tests.outcome.exit_set import owed_union
    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        reduce_block_to_exitset,
    )

    parts: list = []
    earlier_bits: list = []
    guard_owed: tuple = ()

    if not isinstance(guard_out, ExitSet):
        raise NotImplementedError(
            f"match guard outcome not lifted: {type(guard_out).__name__}"
        )
    for face in guard_out.exits:
        if isinstance(face, Halted):
            parts.append(_after(None, owed, _halted_face(face, reached)))
            # Only this polarity of the match is consumed by the halt.
            earlier_bits.append(_and_parts(match_formula, face.guard))
            continue
        if isinstance(face, Completed):
            truth = _formula_from_floor_value(face.value, site)
            selection = _and_parts(reached, face.guard, truth)
            body_exits = reduce_block_to_exitset(body, body_ctx)
            parts.append(_after(selection, owed_union(owed, face.owed), body_exits))
            earlier_bits.append(_and_parts(match_formula, face.guard, truth))
            guard_owed = owed_union(guard_owed, face.owed)
            continue
        raise NotImplementedError(
            f"match guard ExitSet face not lifted: {type(face).__name__}"
        )
    return parts, earlier_bits, guard_owed


@dataclass(frozen=True)
class MatchSugar(Sugar):
    subject: Sugar
    cases: tuple  # MatchCaseSpec, in source order
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        return _call_return_pair(
            name="match_value_return",
            owner_sugar="MatchSugar",
            body="1 if z == 1 else 0",
            truthful="1",
            lying="2",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.ir import or_
        from sugar_lift_py_tests.outcome.exit_set import true_guard
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            plain_completed_value,
            reduce_block_to_exitset,
        )

        subject_out = self.subject.desugar(ctx)
        if not isinstance(subject_out, ExitSet):
            raise NotImplementedError(
                f"match subject outcome not lifted: {type(subject_out).__name__}"
            )
        if subject_out.exits and subject_out.halts() == subject_out.exits:
            # Subject halt is before any case; no later case can run.
            return subject_out
        subject = plain_completed_value(subject_out)
        if subject is None:
            # Multi-face subject: fan the whole match under each completed face.
            # Halted subject faces preserve state under their own guards.
            from sugar_lift_py_tests.outcome import Completed, Halted

            parts = ExitSet(())
            for face in subject_out.exits:
                if isinstance(face, Halted):
                    parts = parts.union(_halted_face(face, true_guard()))
                    continue
                if isinstance(face, Completed):
                    # Re-enter with a constant subject sugar is not needed:
                    # recurse by building a one-shot match over the face's
                    # value via a synthetic sugar wrapper.
                    sub = _CompleteValueSugar(face.value, self.site)
                    nested = MatchSugar(sub, self.cases, self.site).desugar(ctx)
                    # Sequenced under the face: its guard, its partition
                    # testimony and what it owes ride onto every nested arm.
                    parts = parts.union(
                        ExitSet((face,)).sequence(lambda _value, n=nested: n)
                    )
            if parts.exits:
                return parts.normalize()
            from sugar_lift_py_tests.floor.block_value import BlockValue

            return ExitSet.completed(BlockValue((), can_fall_through=True))

        from sugar_lift_py_tests.outcome.exit_set import owed_union

        accumulated = ExitSet(())
        earlier: list = []  # selection formulas of prior *selected* cases
        # What every path past the cases so far incurred: the completed faces
        # of their patterns, equalities and guards (#7757). A case is reached
        # only after every earlier case's pattern ran, so its arms owe this.
        running_owed: tuple = ()

        for case in self.cases:
            if not isinstance(case, MatchCaseSpec):
                raise TypeError(
                    f"MatchSugar.cases requires MatchCaseSpec, got {type(case).__name__}"
                )

            not_prev = _not_earlier(earlier)

            # --- pattern match (all exceptional faces restricted by not_prev) ---
            match_formula, pattern_side, pattern_owed = (
                _pattern_match_formula_and_side_exits(
                    subject, case.alternatives, self.site, not_prev, ctx
                )
            )
            accumulated = accumulated.union(_after(None, running_owed, pattern_side))
            running_owed = owed_union(running_owed, pattern_owed)

            if match_formula is None:
                # No completed match formula: only exceptional pattern faces.
                # Do not claim this case selected; later cases still compete
                # under not_prev (already on those exceptional faces).
                continue

            reached = _and_parts(not_prev, match_formula)

            # --- tentative capture for guard; rolled back after this case ---
            guard_ctx = _tentative_capture_ctx(ctx, case.capture_name, subject)
            body_ctx = _tentative_capture_ctx(ctx, case.capture_name, subject)

            if case.guard is None:
                body_exits = reduce_block_to_exitset(case.body, body_ctx)
                accumulated = accumulated.union(
                    _after(reached, running_owed, body_exits)
                )
                earlier.append(match_formula)
                continue

            guard_out = case.guard.desugar(guard_ctx)
            parts, earlier_bits, guard_owed = _guard_faces_under(
                guard_out,
                reached,
                self.site,
                case.body,
                body_ctx,
                match_formula,
                running_owed,
            )
            for part in parts:
                accumulated = accumulated.union(part)
            running_owed = owed_union(running_owed, guard_owed)
            # Collapse earlier_bits: any selection of this case for first-case-wins.
            if earlier_bits:
                # Distinct polarities: later cases see not(OR of selections).
                if len(earlier_bits) == 1:
                    earlier.append(earlier_bits[0])
                else:
                    earlier.append(or_(tuple(earlier_bits)))
            # body_ctx / guard_ctx discarded here — rollback for next case.

        if not accumulated.exits:
            from sugar_lift_py_tests.floor.block_value import BlockValue

            return _after(
                None,
                running_owed,
                ExitSet.completed(BlockValue((), can_fall_through=True)),
            )
        # Shared ExitSet projection — no output-kind membrane on value shape.
        return accumulated.normalize()


@dataclass(frozen=True)
class _CompleteValueSugar(Sugar):
    """One-shot sugar that desugars to an already-reduced FloorValue."""

    value: object
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None) -> Outcome:
        del ctx
        return ExitSet.completed(self.value)
