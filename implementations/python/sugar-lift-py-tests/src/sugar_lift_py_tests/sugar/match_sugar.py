"""`match subject: case P [if g]: body ...` -- structural pattern matching.

A match is sequential, first-case-wins: case i runs exactly when the subject
matches P_i, matched no earlier *selected* case, and its guard (if any) is true.

Subject evaluates ONCE. Pattern captures bind the subject for that case's
guard and body only:

  - tentative bind for guard evaluation
  - false guard rolls the tentative bind back before the next case
  - true guard commits the bind for the body under the selection formula
  - guard halt bypasses later cases under the matched-and-reached-guard path,
    carrying the halt's pre-effect state

Value patterns (`case <literal>:`) and catch-all / bare capture
(`case _:` / `case x:`) are owned. Structural patterns stay loud at the
construction door (nodes.py); this sugar never admits by spelling scan.
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
        from sugar_lift_py_tests.floor.block_value import BlockValue
        from sugar_lift_py_tests.ir import and_, not_, or_
        from sugar_lift_py_tests.outcome import Incomplete
        from sugar_lift_py_tests.outcome.exit_set import true_guard
        from sugar_lift_py_tests.sugar.function_universe_sugar import reduce_statements
        from sugar_lift_py_tests.sugar.if_sugar import predicate_formula

        subject_out = self.subject.desugar(ctx)
        if isinstance(subject_out, Incomplete):
            return subject_out
        # Subject evaluated once; every case compares / binds against this value.
        subject = subject_out.value

        entries: list = []
        earlier: list = []  # selection formulas of prior *selected* cases
        for case in self.cases:
            if not isinstance(case, MatchCaseSpec):
                raise TypeError(
                    f"MatchSugar.cases requires MatchCaseSpec, got {type(case).__name__}"
                )

            # --- pattern match formula (value alternatives or always-match) ---
            if not case.alternatives:
                match_formula = true_guard()  # catch-all / bare capture
            else:
                alts = []
                for alt in case.alternatives:
                    alt_out = alt.desugar(ctx)
                    if isinstance(alt_out, Incomplete):
                        return alt_out
                    eq_out = subject.equals(alt_out.value, self.site)
                    if isinstance(eq_out, Incomplete):
                        return eq_out
                    # Ground TermValue equality folds to True/False bool sugars;
                    # symbolic equality carries a predicate formula.
                    formula = getattr(getattr(eq_out, "value", None), "formula", None)
                    if formula is None:
                        formula = predicate_formula(eq_out.value, self.site)
                    alts.append(formula)
                match_formula = or_(tuple(alts)) if len(alts) > 1 else alts[0]

            not_prev = _not_earlier(earlier)
            reached = _and_parts(not_prev, match_formula)

            # --- tentative capture for guard (rolled back after this case) ---
            guard_ctx = _tentative_capture_ctx(ctx, case.capture_name, subject)

            guard_formula = true_guard()
            if case.guard is not None:
                from sugar_lift_py_tests.outcome import ExitSet

                guard_out = case.guard.desugar(guard_ctx)
                if isinstance(guard_out, Incomplete):
                    # Guard halt under reached pattern: later cases do not run
                    # on this path. Pre-halt state rides on the Incomplete face.
                    entries.append(guard_out.guarded(reached))
                    # Pattern path is consumed by the halt (not available later).
                    earlier.append(match_formula)
                    continue
                if isinstance(guard_out, ExitSet):
                    # Dual-face guard (e.g. undecided compare): hoist Incomplete
                    # halt faces under reached; take Completed face formula as guard.
                    from sugar_lift_py_tests.outcome import Halted, Completed

                    for face in guard_out.exits:
                        if isinstance(face, Halted):
                            entries.append(
                                Incomplete(face.effect).guarded(
                                    _and_parts(reached, face.guard)
                                )
                            )
                    completed = [
                        face
                        for face in guard_out.exits
                        if isinstance(face, Completed)
                    ]
                    if not completed:
                        earlier.append(match_formula)
                        continue
                    try:
                        guard_formula = predicate_formula(
                            completed[0].value, self.site
                        )
                    except NotImplementedError:
                        raise
                elif isinstance(guard_out, Complete):
                    try:
                        guard_formula = predicate_formula(guard_out.value, self.site)
                    except NotImplementedError:
                        raise
                else:
                    raise NotImplementedError(
                        f"match guard outcome not lifted: {type(guard_out).__name__}"
                    )
            # selection = not earlier selected AND pattern match AND guard true
            selection = _and_parts(not_prev, match_formula, guard_formula)

            # Commit capture for body only under selection (true-guard path).
            # False-guard path never reduces the body; body_ctx is discarded
            # before the next case (rollback — next case uses original ctx).
            body_ctx = _tentative_capture_ctx(ctx, case.capture_name, subject)
            body_entries, _falls, _ft = reduce_statements(case.body, body_ctx)
            if selection == true_guard() and not earlier:
                entries.extend(body_entries)
            else:
                entries.extend(entry.guarded(selection) for entry in body_entries)

            # First-case-wins: later cases see not(match ∧ guard_true).
            # False guard leaves match∧false, so later cases still see the match path.
            earlier.append(_and_parts(match_formula, guard_formula))

        return Complete(BlockValue(tuple(entries), can_fall_through=True))