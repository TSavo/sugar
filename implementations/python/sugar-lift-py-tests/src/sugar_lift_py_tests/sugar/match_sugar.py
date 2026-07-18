from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair, typed_red_effect_witness
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class MatchCase:
    pattern: SugarBody
    guard: SugarBody | None
    body: SugarBody


@dataclass(frozen=True)
class MatchSugar(Sugar, role=SugarRole.STATEMENT):
    """Reduce decidable match cases; preserve runtime selection as typed red.

    Ground literal, singleton, OR, capture, and wildcard patterns select their
    first matching case in source order. A runtime subject or guard cannot
    choose a case during lift, so it becomes a named effect. A ground subject
    meeting an unsupported pattern is a construction gap and remains a loud
    ``MatchSugar`` panic rather than being mislabeled as runtime uncertainty.
    """

    subject: SugarBody
    cases: tuple[MatchCase, ...]
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "Match"

    @classmethod
    def new(cls, site, ctx) -> "MatchSugar":
        return cls(
            subject=ctx.build_body(site.match_subject(), SugarRole.TERM),
            cases=tuple(
                MatchCase(
                    pattern=ctx.build_body(pattern, SugarRole.PATTERN),
                    guard=(
                        ctx.build_body(guard, SugarRole.TERM)
                        if guard is not None
                        else None
                    ),
                    body=ctx.build_body(body, SugarRole.STATEMENT),
                )
                for pattern, guard, body in site.match_cases()
            ),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        prefix = (
            "def A():\n"
            "    match 2:\n"
            "        case 1:\n"
            "            return 10\n"
            "        case 2:\n"
            "            return 20\n"
            "        case _:\n"
            "            return 30\n"
            "\n"
        )
        return (
            _call_pair(
                name="match_literal_case_return",
                owner_sugar="MatchSugar",
                truthful=prefix + "def test_a():\n    assert A() == 20\n",
                lying=prefix + "def test_a():\n    assert A() == 30\n",
                family="literal-match",
            ),
            typed_red_effect_witness(
                name="match_runtime_subject_effect",
                owner_sugar="MatchSugar",
                source=(
                    "def A(value):\n"
                    "    match value:\n"
                    "        case 1:\n"
                    "            return 10\n"
                    "        case _:\n"
                    "            return 20\n"
                ),
                effect_class="MatchSelectionRuntimeEffect",
                reason_needle="runtime match selection",
                blame_needle="test_witness.py:2:4",
                wrong_reason_needle="unsupported MatchSequence",
            ),
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return self.subject.reduce(ctx).and_then(
            lambda subject: self._select(subject, self.cases, ctx)
        )

    def _select(self, subject, cases: tuple[MatchCase, ...], ctx) -> Outcome:
        from sugar_lift_py_tests.sugar.match_pattern_sugar import ground_match_value

        known, subject_value = ground_match_value(subject)
        if not known:
            return _runtime_selection(
                subject,
                self.site,
                "runtime match selection: Python must evaluate the subject "
                "before choosing a case",
            )
        return self._select_ground(subject, subject_value, cases, ctx)

    def _select_ground(self, subject, subject_value, cases, ctx) -> Outcome:
        if not cases:
            from sugar_lift_py_tests.floor import BlockValue

            return Complete(BlockValue(()))
        case, *rest = cases
        return case.pattern.reduce(ctx).and_then(
            lambda pattern: pattern.select_ground(
                subject_value,
                matched=lambda capture: self._select_matched(
                    case,
                    capture,
                    subject,
                    subject_value,
                    tuple(rest),
                    ctx,
                ),
                missed=lambda: self._select_ground(
                    subject, subject_value, tuple(rest), ctx
                ),
                ctx=ctx,
            )
        )

    def _select_matched(
        self,
        case,
        capture,
        subject,
        subject_value,
        rest,
        ctx,
    ) -> Outcome:
        case_ctx = ctx
        if capture is not None:
            from sugar_lift_py_tests.floor import ScopeRebind

            case_ctx = ScopeRebind(capture, subject).extend_scope(ctx)
        if case.guard is None:
            return case.body.reduce(case_ctx)
        return case.guard.reduce(case_ctx).and_then(
            lambda guard: self._select_guarded(
                guard,
                case,
                subject,
                subject_value,
                tuple(rest),
                ctx,
                case_ctx,
            )
        )

    def _select_guarded(
        self,
        guard,
        case,
        subject,
        subject_value,
        rest,
        ctx,
        case_ctx,
    ) -> Outcome:
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        if type(guard) is TrueBoolLiteralSugar:
            return case.body.reduce(case_ctx)
        if type(guard) is FalseBoolLiteralSugar:
            return self._select_ground(subject, subject_value, rest, ctx)
        return _runtime_selection(
            guard,
            self.site,
            "runtime match selection: Python must evaluate the case guard before "
            "choosing its body",
        )

    def walk_children(self):
        return (
            self.subject,
            *(
                child
                for case in self.cases
                for child in ((case.guard,) if case.guard is not None else ())
            ),
            *(case.pattern for case in self.cases),
            *(case.body for case in self.cases),
        )


def _runtime_selection(operand, site, reason: str) -> Incomplete:
    from sugar_lift_py_tests.effect import (
        MatchSelectionRuntimeEffect,
        runtime_effect_evidence_from_terms,
    )
    from sugar_lift_py_tests.ir import ctor

    term = operand.to_term(owner="MatchSugar runtime selection")
    return Incomplete(
        MatchSelectionRuntimeEffect(
            f"{reason}; blame={site}",
            **runtime_effect_evidence_from_terms(
                ctor("py.match.select", [term]),
                term,
                site,
            ),
        )
    )
