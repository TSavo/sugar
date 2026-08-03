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

Value patterns and catch-all / bare capture are owned. Structural patterns
stay loud at the construction door (nodes.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Complete, Outcome
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


def _restrict(exits, guard):
    """Restrict an ExitSet by guard, preserving Halted.state and pending contracts."""
    from sugar_lift_py_tests.outcome.exit_set import ExitSet, true_guard

    if guard is None or guard == true_guard():
        return exits
    return exits.guarded(guard)


def _halted_face(face, prefix_guard):
    """Preserve a Halted face (effect + state + owed) under an outer prefix."""
    from sugar_lift_py_tests.outcome.exit_set import ExitSet, Halted

    combined = _and_parts(prefix_guard, face.guard)
    return ExitSet(
        (
            Halted(
                combined,
                face.effect,
                face.state,
                face.faces,
                face.pending_contracts,
            ),
        )
    )


def _incomplete_as_halted(incomplete, prefix_guard):
    """Incomplete has no state; Halted under prefix with state=None is honest."""
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
    from sugar_lift_py_tests.outcome import Completed, Halted, Incomplete
    from sugar_lift_py_tests.outcome.exit_set import ExitSet

    side = ExitSet(())
    for face in exits.exits:
        if isinstance(face, Completed):
            continue
        if isinstance(face, Halted):
            side = side.union(_halted_face(face, prefix_guard))
        elif isinstance(face, Incomplete):
            side = side.union(_incomplete_as_halted(face, prefix_guard))
        else:
            raise NotImplementedError(
                f"match side face not lifted: {type(face).__name__}"
            )
    return side


def _pattern_match_formula_and_side_exits(subject, alternatives, site, not_prev, ctx):
    """Build match formula; exceptional alt/equality faces ride under not_prev.

    Returns ``(match_formula | None, side_exits: ExitSet)``.
    Completed faces of alternative/equality ExitSets feed matching ONLY —
    they are never unioned wholesale into the Match outcome.
    """
    from sugar_lift_py_tests.ir import or_
    from sugar_lift_py_tests.outcome import Complete, Completed, Incomplete
    from sugar_lift_py_tests.outcome.exit_set import ExitSet, true_guard

    if not alternatives:
        return true_guard(), ExitSet(())

    alts = []
    side = ExitSet(())
    for alt in alternatives:
        alt_out = alt.desugar(ctx)
        if isinstance(alt_out, Incomplete):
            side = side.union(_incomplete_as_halted(alt_out, not_prev))
            continue
        if isinstance(alt_out, ExitSet):
            # Exceptional/control faces only — not Completed outcomes.
            side = side.union(_exceptional_faces_only(alt_out, not_prev))
            for face in alt_out.exits:
                if not isinstance(face, Completed):
                    continue
                # Matching under not_prev ∧ alt-face polarity.
                eq_prefix = _and_parts(not_prev, face.guard)
                eq_out = subject.equals(face.value, site)
                side, formula = _equality_outcome_under(eq_out, eq_prefix, site, side)
                if formula is not None:
                    # Alt polarity is already in formula when equality is Complete;
                    # when multi-face equality, formula is OR of (face.guard ∧ truth).
                    alts.append(_and_parts(face.guard, formula))
            continue
        if not isinstance(alt_out, Complete):
            raise NotImplementedError(
                f"match alternative outcome not lifted: {type(alt_out).__name__}"
            )
        eq_out = subject.equals(alt_out.value, site)
        side, formula = _equality_outcome_under(eq_out, not_prev, site, side)
        if formula is not None:
            alts.append(formula)

    if not alts:
        return None, side
    match_formula = or_(tuple(alts)) if len(alts) > 1 else alts[0]
    return match_formula, side


def _equality_outcome_under(eq_out, not_prev, site, side):
    """Process subject.equals under not_prev; return (side, formula|None).

    ExitSet Completed faces contribute ``face.guard ∧ truth(face.value)`` to
    the match formula only. Non-completed faces propagate separately (state
    preserved). Never wholesale-unions Completed equality faces into side.
    """
    from sugar_lift_py_tests.ir import or_
    from sugar_lift_py_tests.outcome import Complete, Completed, Halted, Incomplete
    from sugar_lift_py_tests.outcome.exit_set import ExitSet

    if isinstance(eq_out, Incomplete):
        return side.union(_incomplete_as_halted(eq_out, not_prev)), None
    if isinstance(eq_out, ExitSet):
        formulas = []
        for face in eq_out.exits:
            if isinstance(face, Halted):
                side = side.union(_halted_face(face, not_prev))
                continue
            if isinstance(face, Completed):
                truth = _formula_from_floor_value(face.value, site)
                formulas.append(_and_parts(face.guard, truth))
                continue
            if isinstance(face, Incomplete):
                side = side.union(_incomplete_as_halted(face, not_prev))
                continue
            raise NotImplementedError(
                f"match equality face not lifted: {type(face).__name__}"
            )
        if not formulas:
            return side, None
        formula = or_(tuple(formulas)) if len(formulas) > 1 else formulas[0]
        return side, formula
    if isinstance(eq_out, Complete):
        return side, _formula_from_floor_value(eq_out.value, site)
    raise NotImplementedError(
        f"match equality outcome not lifted: {type(eq_out).__name__}"
    )


def _guard_faces_under(guard_out, reached, site, body, body_ctx, match_formula):
    """Fan a guard outcome into ExitSets under ``reached``; return (parts, earlier_bits).

    Per Completed face: body under ``reached ∧ face.guard ∧ truth``.
    Per Halted face: preserve Halted under ``reached ∧ face.guard``; mark only
    ``match_formula ∧ face.guard`` consumed (not the whole match path).
    """
    from sugar_lift_py_tests.outcome import Complete, Completed, Halted, Incomplete
    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        reduce_block_to_exitset,
    )

    parts: list = []
    earlier_bits: list = []

    from sugar_lift_py_tests.outcome.exit_set import ExitSet

    if isinstance(guard_out, Incomplete):
        parts.append(_incomplete_as_halted(guard_out, reached))
        # No face polarity: whole reached path is consumed by the halt.
        earlier_bits.append(match_formula)
        return parts, earlier_bits

    if isinstance(guard_out, ExitSet):
        for face in guard_out.exits:
            if isinstance(face, Halted):
                parts.append(_halted_face(face, reached))
                # Only this polarity of the match is consumed by the halt.
                earlier_bits.append(_and_parts(match_formula, face.guard))
                continue
            if isinstance(face, Completed):
                truth = _formula_from_floor_value(face.value, site)
                selection = _and_parts(reached, face.guard, truth)
                body_exits = reduce_block_to_exitset(body, body_ctx)
                parts.append(_restrict(body_exits, selection))
                earlier_bits.append(_and_parts(match_formula, face.guard, truth))
                continue
            if isinstance(face, Incomplete):
                parts.append(_incomplete_as_halted(face, reached))
                earlier_bits.append(match_formula)
                continue
            raise NotImplementedError(
                f"match guard ExitSet face not lifted: {type(face).__name__}"
            )
        return parts, earlier_bits

    if isinstance(guard_out, Complete):
        truth = _formula_from_floor_value(guard_out.value, site)
        selection = _and_parts(reached, truth)
        body_exits = reduce_block_to_exitset(body, body_ctx)
        parts.append(_restrict(body_exits, selection))
        earlier_bits.append(_and_parts(match_formula, truth))
        return parts, earlier_bits

    raise NotImplementedError(
        f"match guard outcome not lifted: {type(guard_out).__name__}"
    )


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
        from sugar_lift_py_tests.outcome import Incomplete
        from sugar_lift_py_tests.outcome.exit_set import ExitSet, true_guard
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            reduce_block_to_exitset,
        )

        subject_out = self.subject.desugar(ctx)
        if isinstance(subject_out, Incomplete):
            # Subject halt is before any case; no later case can run.
            return subject_out
        if isinstance(subject_out, ExitSet):
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
                    # recurse by building a one-shot match over Complete value
                    # via a synthetic sugar wrapper.
                    sub = _CompleteValueSugar(face.value, self.site)
                    nested = MatchSugar(sub, self.cases, self.site).desugar(ctx)
                    nested_es = _outcome_as_exitset(nested)
                    parts = parts.union(_restrict(nested_es, face.guard))
            return (
                parts.normalize()
                if parts.exits
                else Complete(
                    __import__(
                        "sugar_lift_py_tests.floor.block_value", fromlist=["BlockValue"]
                    ).BlockValue((), can_fall_through=True)
                )
            )

        if not isinstance(subject_out, Complete):
            raise NotImplementedError(
                f"match subject outcome not lifted: {type(subject_out).__name__}"
            )
        subject = subject_out.value

        accumulated = ExitSet(())
        earlier: list = []  # selection formulas of prior *selected* cases

        for case in self.cases:
            if not isinstance(case, MatchCaseSpec):
                raise TypeError(
                    f"MatchSugar.cases requires MatchCaseSpec, got {type(case).__name__}"
                )

            not_prev = _not_earlier(earlier)

            # --- pattern match (all exceptional faces restricted by not_prev) ---
            match_formula, pattern_side = _pattern_match_formula_and_side_exits(
                subject, case.alternatives, self.site, not_prev, ctx
            )
            accumulated = accumulated.union(pattern_side)

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
                accumulated = accumulated.union(_restrict(body_exits, reached))
                earlier.append(match_formula)
                continue

            guard_out = case.guard.desugar(guard_ctx)
            parts, earlier_bits = _guard_faces_under(
                guard_out,
                reached,
                self.site,
                case.body,
                body_ctx,
                match_formula,
            )
            for part in parts:
                accumulated = accumulated.union(part)
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

            return Complete(BlockValue((), can_fall_through=True))
        # Shared ExitSet projection — no output-kind membrane on value shape.
        return accumulated.normalize().collapse()


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
        return Complete(self.value)


def _outcome_as_exitset(outcome):
    from sugar_lift_py_tests.outcome import Complete, Incomplete
    from sugar_lift_py_tests.outcome.exit_set import ExitSet, outcome_to_exitset

    if isinstance(outcome, ExitSet):
        return outcome
    if isinstance(outcome, Incomplete):
        return ExitSet.halted(outcome.effect)
    if isinstance(outcome, Complete):
        return ExitSet.completed(outcome.value)
    return outcome_to_exitset(outcome)
