"""`match subject: case P: body ...` -- structural pattern matching.

A match is sequential, first-case-wins: case i runs exactly when the subject
matches P_i AND matched no earlier case. So it is an n-way guarded split, the
same shape as `if`/`elif`/`else`: each case's body facts ride under
`matches(subject, P_i) AND NOT matches(subject, P_<i)`, and a guarded fact IS an
implication (the GuardedValue.guarded / entry.guarded vocabulary).

This first cut owns the VALUE-pattern subset: `case <literal>:` (the subject
equals that value) and the wildcard `case _:` (the catch-all, guarded only by
the negation of every earlier case). Captures (`case x:`), pattern guards
(`case P if g:`), OR-patterns, singletons, and structural patterns (sequence /
mapping / class / star) stay LOUD -- each is real matching semantics, and
guessing one would invent a constraint the source never stated. The subject is
reduced ONCE (Python evaluates it once); every case compares against it.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_return_pair


@dataclass(frozen=True)
class MatchCaseSpec:
    """One case: the value-pattern alternatives it matches and its body sugars.

    ``alternatives`` is the tuple of literal sugars the subject may equal --
    ``(1,)`` for `case 1:`, ``(1, 2)`` for the OR-pattern `case 1 | 2:`, and the
    EMPTY tuple for a catch-all (`case _:` or a capture `case x:`, both of which
    always match)."""

    alternatives: tuple  # literal sugars; empty = catch-all
    body: tuple


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
            body="1 if z == 1 else 0",  # a match on z is an if-chain in spirit
            truthful="1",
            lying="2",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.floor.block_value import BlockValue
        from sugar_lift_py_tests.ir import and_, not_, or_
        from sugar_lift_py_tests.outcome import Incomplete
        from sugar_lift_py_tests.sugar.function_universe_sugar import reduce_statements

        subject_out = self.subject.desugar(ctx)
        if isinstance(subject_out, Incomplete):
            return subject_out
        subject = subject_out.value

        entries: list = []
        earlier: list = []  # match formulas of the cases before this one
        for case in self.cases:
            body_entries, _falls, _ft = reduce_statements(case.body)

            if not case.alternatives:  # catch-all (`case _:` / capture)
                match_formula = None
            else:
                # `case a | b:` matches iff the subject equals ANY alternative.
                alts = []
                for alt in case.alternatives:
                    alt_out = alt.desugar(ctx)
                    if isinstance(alt_out, Incomplete):
                        return alt_out
                    eq_out = subject.equals(alt_out.value, self.site)
                    formula = getattr(getattr(eq_out, "value", None), "formula", None)
                    if formula is None:
                        raise NotImplementedError(
                            "match value pattern whose equality is not a predicate "
                            "is not lifted yet (ground fold): symbolic sides only"
                        )
                    alts.append(formula)
                match_formula = or_(tuple(alts)) if len(alts) > 1 else alts[0]

            if match_formula is None:
                guard = and_(tuple(not_(f) for f in earlier)) if earlier else None
            else:
                clause = tuple(not_(f) for f in earlier) + (match_formula,)
                guard = and_(clause) if len(clause) > 1 else match_formula
                earlier.append(match_formula)

            if guard is None:  # a catch-all with no earlier cases: unconditional
                entries.extend(body_entries)
            else:
                entries.extend(entry.guarded(guard) for entry in body_entries)

        return Complete(BlockValue(tuple(entries), can_fall_through=True))
