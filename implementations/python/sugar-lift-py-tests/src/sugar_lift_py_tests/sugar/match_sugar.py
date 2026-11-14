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
  - a match with no catch-all case has a fall-through arm: completed under
    the negation of every case's selection, owing what every failed
    equality, pattern and guard owed (#7757)
  - each case's body arms and the fall-through arm are the match's routes
    (``route_site``, minted by ``Match.substitute`` when a binding after the
    match joins over them): every completed arm of a route confirms the
    match's route slots -- its own true, every other false -- and grounds
    them for the code after it, as a ``try``'s routed outcome does
    (``try_sugar._route_confirmation``, ``_ground_route_on_faces``)

Value patterns and catch-all / bare capture are owned. Structural patterns
stay loud at the construction door (nodes.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import ExitSet
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


def _debt(owed=()):
    """One completed match step under truth owing ``owed``.

    The match's PATH is one such arm: what the patterns, equalities and
    guards run so far incurred. It grows only by composition --
    ``path.sequence(lambda _: step)`` for a step that ran after it, and
    ``ExitSet.union`` for sibling faces of one step, which merges them into
    one arm owing every sibling's debt -- never by unioning debts by hand.
    """
    from sugar_lift_py_tests.outcome import Completed
    from sugar_lift_py_tests.outcome.exit_set import true_guard

    return ExitSet((Completed(true_guard(), None, owed=owed),))


def _then(path, step):
    """``path`` followed by ``step``: one arm owing both, in that order."""
    return path.sequence(lambda _reached: step)


def _after(guard, path, exits):
    """``exits`` sequenced after the match ``path`` that reached them (#7757).

    ``path`` is the one-arm match step (``_debt``) owing what the patterns,
    equalities and guards on the path into these arms incurred, restricted
    here to ``guard``. ``ExitSet.sequence`` conjoins ``guard`` onto every arm
    and carries the debt onto every arm, completed and halted alike, so
    nothing a completed equality or guard face owed is dropped by being read
    as a formula only. Halted.state and partition faces ride through
    unchanged.
    """
    reached = path if guard is None else path.guarded(guard)
    return reached.sequence(lambda _reached: exits)


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

    Returns ``(match_formula | None, side_exits: ExitSet, pattern_path)``.
    Completed faces of alternative/equality ExitSets feed matching as
    formulas, and what they OWE is returned as ``pattern_path`` (one
    ``_debt`` arm) for the caller to sequence every arm past this pattern
    after (#7757). They are never unioned wholesale into the Match outcome.
    An equality halt is sequenced after the alternative that completed into
    it, so it owes what that alternative (and every alternative tried before
    it) owed.
    """
    from sugar_lift_py_tests.ir import or_
    from sugar_lift_py_tests.outcome import Completed
    from sugar_lift_py_tests.outcome.exit_set import true_guard

    if not alternatives:
        return true_guard(), ExitSet(()), _debt()

    alts = []
    side = ExitSet(())
    path = _debt()
    for alt in alternatives:
        alt_out = alt.desugar(ctx)
        if not isinstance(alt_out, ExitSet):
            raise NotImplementedError(
                f"match alternative outcome not lifted: {type(alt_out).__name__}"
            )
        # What the alternatives tried before this one incurred.
        before = path
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
            eq_side, formula, eq_path = _equality_outcome_under(
                eq_out, eq_prefix, site
            )
            # The equality ran after this alternative's face completed.
            reached_eq = _then(before, _debt(face.owed))
            side = side.union(_after(None, reached_eq, eq_side))
            path = _then(_then(path, _debt(face.owed)), eq_path)
            if formula is not None:
                # When multi-face equality, formula is OR of (face.guard ∧ truth).
                alts.append(_and_parts(face.guard, formula))

    if not alts:
        return None, side, path
    match_formula = or_(tuple(alts)) if len(alts) > 1 else alts[0]
    return match_formula, side, path


def _equality_outcome_under(eq_out, not_prev, site):
    """Process subject.equals under not_prev; return (side, formula|None, path).

    ExitSet Completed faces contribute ``face.guard ∧ truth(face.value)`` to
    the match formula, and their ``owed`` to the returned ``path`` (#7757):
    the equality ran on every path past it, so the caller sequences every
    such arm after it. The completed faces are siblings of one comparison,
    so ``path`` is their join (``ExitSet.union`` of one ``_debt`` arm each):
    one arm owing every face's debt. Non-completed faces propagate
    separately (state and owed preserved). Never wholesale-unions Completed
    equality faces into side.
    """
    from sugar_lift_py_tests.ir import or_
    from sugar_lift_py_tests.outcome import Completed, Halted

    if not isinstance(eq_out, ExitSet):
        raise NotImplementedError(
            f"match equality outcome not lifted: {type(eq_out).__name__}"
        )
    side = ExitSet(())
    formulas = []
    path = _debt()
    for face in eq_out.exits:
        if isinstance(face, Halted):
            side = side.union(_halted_face(face, not_prev))
            continue
        if isinstance(face, Completed):
            truth = _formula_from_floor_value(face.value, site)
            formulas.append(_and_parts(face.guard, truth))
            path = path.union(_debt(face.owed))
            continue
        raise NotImplementedError(
            f"match equality face not lifted: {type(face).__name__}"
        )
    if not formulas:
        return side, None, path
    formula = or_(tuple(formulas)) if len(formulas) > 1 else formulas[0]
    return side, formula, path


def _guard_faces_under(
    guard_out, reached, site, body, body_ctx, match_formula, path, routed
):
    """Fan a guard outcome into ExitSets under ``reached``.

    Returns ``(parts, earlier_bits, guard_path)``.  ``routed`` turns the
    body's exits into the case's route (``MatchSugar._routed``).

    ``path`` is the match step owing what the path into this guard incurred
    (patterns and equalities of this and every earlier case); every part is
    sequenced after it. Per Completed face: body sequenced under ``reached ∧
    face.guard ∧ truth``, after ``path`` and then the face. Per Halted face:
    preserve Halted under ``reached ∧ face.guard``; mark only ``match_formula
    ∧ face.guard`` consumed (not the whole match path). ``guard_path`` is the
    join of every completed face's debt (``ExitSet.union``), which the paths
    past a false guard carry too (#7757).
    """
    from sugar_lift_py_tests.outcome import Completed, Halted
    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        reduce_block_to_exitset,
    )

    parts: list = []
    earlier_bits: list = []
    guard_path = _debt()

    if not isinstance(guard_out, ExitSet):
        raise NotImplementedError(
            f"match guard outcome not lifted: {type(guard_out).__name__}"
        )
    for face in guard_out.exits:
        if isinstance(face, Halted):
            parts.append(_after(None, path, _halted_face(face, reached)))
            # Only this polarity of the match is consumed by the halt.
            earlier_bits.append(_and_parts(match_formula, face.guard))
            continue
        if isinstance(face, Completed):
            truth = _formula_from_floor_value(face.value, site)
            selection = _and_parts(reached, face.guard, truth)
            body_exits = routed(reduce_block_to_exitset(body, body_ctx))
            parts.append(
                _after(selection, _then(path, _debt(face.owed)), body_exits)
            )
            earlier_bits.append(_and_parts(match_formula, face.guard, truth))
            guard_path = guard_path.union(_debt(face.owed))
            continue
        raise NotImplementedError(
            f"match guard ExitSet face not lifted: {type(face).__name__}"
        )
    return parts, earlier_bits, guard_path


@dataclass(frozen=True)
class MatchSugar(Sugar):
    subject: Sugar
    cases: tuple  # MatchCaseSpec, in source order
    site: object = dataclass_field(compare=False)
    # The address of the match's route slots (``match_route_site``), when a
    # binding after the match joins over them (``Match.substitute``); None
    # when nothing reads them.
    route_site: object = dataclass_field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        return _call_return_pair(
            name="match_value_return",
            owner_sugar="MatchSugar",
            body="1 if z == 1 else 0",
            truthful="1",
            lying="2",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
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
                    nested = MatchSugar(
                        sub, self.cases, self.site, self.route_site
                    ).desugar(ctx)
                    # Sequenced under the face: its guard, its partition
                    # testimony and what it owes ride onto every nested arm.
                    parts = parts.union(
                        ExitSet((face,)).sequence(lambda _value, n=nested: n)
                    )
            if parts.exits:
                return parts.normalize()
            from sugar_lift_py_tests.floor.block_value import BlockValue

            return ExitSet.completed(BlockValue((), can_fall_through=True))

        accumulated = ExitSet(())
        earlier: list = []  # selection formulas of prior *selected* cases
        # The match step every path past the cases so far took: it owes what
        # the completed faces of their patterns, equalities and guards owed
        # (#7757). A case is reached only after every earlier case's pattern
        # ran, so its arms are sequenced after this.
        running = _debt()

        for arm, case in enumerate(self.cases):
            if not isinstance(case, MatchCaseSpec):
                raise TypeError(
                    f"MatchSugar.cases requires MatchCaseSpec, got {type(case).__name__}"
                )

            not_prev = _not_earlier(earlier)

            # --- pattern match (all exceptional faces restricted by not_prev) ---
            match_formula, pattern_side, pattern_path = (
                _pattern_match_formula_and_side_exits(
                    subject, case.alternatives, self.site, not_prev, ctx
                )
            )
            accumulated = accumulated.union(_after(None, running, pattern_side))
            running = _then(running, pattern_path)

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
                body_exits = self._routed(
                    arm, reduce_block_to_exitset(case.body, body_ctx)
                )
                accumulated = accumulated.union(_after(reached, running, body_exits))
                earlier.append(match_formula)
                continue

            guard_out = case.guard.desugar(guard_ctx)
            parts, earlier_bits, guard_path = _guard_faces_under(
                guard_out,
                reached,
                self.site,
                case.body,
                body_ctx,
                match_formula,
                running,
                lambda exits, arm=arm: self._routed(arm, exits),
            )
            for part in parts:
                accumulated = accumulated.union(part)
            running = _then(running, guard_path)
            # Collapse earlier_bits: any selection of this case for first-case-wins.
            if earlier_bits:
                # Distinct polarities: later cases see not(OR of selections).
                if len(earlier_bits) == 1:
                    earlier.append(earlier_bits[0])
                else:
                    earlier.append(or_(tuple(earlier_bits)))
            # body_ctx / guard_ctx discarded here — rollback for next case.

        from sugar_lift_py_tests.outcome.exit_set import _is_true

        if not any(_is_true(selection) for selection in earlier):
            # No case is a catch-all: the path where no case matched is real
            # Python behaviour (execution continues after the match), so it
            # is an arm (#7757). It is completed under the negation of every
            # case's selection and owes what every failed equality, pattern
            # and guard on that path owed.
            from sugar_lift_py_tests.floor.block_value import BlockValue

            # The fall-through route: every case slot is false on it.
            accumulated = accumulated.union(
                _after(
                    _not_earlier(earlier),
                    running,
                    ExitSet.completed(
                        BlockValue(self._route_facts(None), can_fall_through=True)
                    ),
                )
            )
        # Shared ExitSet projection — no output-kind membrane on value shape.
        return accumulated.normalize()

    def _route_facts(self, arm) -> tuple:
        """What a completed arm of route ``arm`` (case ``arm``, or the
        fall-through for ``None``) states about the match's route slots
        (``try_sugar._route_confirmation``); nothing without a route site."""
        from sugar_lift_py_tests.sugar.try_sugar import _route_confirmation

        return _route_confirmation(self.route_site, len(self.cases), arm, self.site)

    def _routed(self, arm, exits):
        """Case ``arm``'s body ``exits`` as the match's route ``arm``: every
        completed arm confirms the route slots (``_route_facts``) and decides
        them for the code after it (``try_sugar._ground_route_on_faces``), so
        a phi after the match (``Match.substitute``) reads that case's
        binding there.  A body still waiting on its caller's actuals is
        routed once they discharge it."""
        if self.route_site is None:
            return exits
        from sugar_lift_py_tests.caller_parameter_contract import (
            NativeOperationExitCarrierV1,
        )
        from sugar_lift_py_tests.sugar.try_sugar import (
            _ground_route_on_faces,
            _prepend_facts,
        )

        if isinstance(exits, NativeOperationExitCarrierV1):
            return exits.after_discharge(
                lambda discharged: self._routed(arm, discharged)
            )
        return _ground_route_on_faces(
            _prepend_facts(exits, self._route_facts(arm)),
            self.route_site,
            len(self.cases),
            arm,
            self.site,
        )


@dataclass(frozen=True)
class _CompleteValueSugar(Sugar):
    """One-shot sugar that desugars to an already-reduced FloorValue."""

    value: object
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None) -> ExitSet:
        del ctx
        return ExitSet.completed(self.value)
