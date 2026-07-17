from __future__ import annotations

import ast
from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory.block import Block
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair, typed_red_effect_witness
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class MatchCase:
    pattern: ast.pattern
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
        from sugar_lift_py_tests.factory.source_fragment import SourceFragment

        def fragment(node):
            return SourceFragment.from_node(node, site.filename, source=site.source)

        return cls(
            subject=ctx.build_body(fragment(site.node.subject), SugarRole.TERM),
            cases=tuple(
                MatchCase(
                    pattern=case.pattern,
                    guard=(
                        ctx.build_body(fragment(case.guard), SugarRole.TERM)
                        if case.guard is not None
                        else None
                    ),
                    body=ctx.build_body(
                        fragment(Block.of(case.body)), SugarRole.STATEMENT
                    ),
                )
                for case in site.node.cases
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
        known, subject_value = _ground_value(subject)
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
        matched, capture = _match_ground(case.pattern, subject_value, self.site)
        if not matched:
            return self._select_ground(subject, subject_value, tuple(rest), ctx)
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
            *(case.body for case in self.cases),
        )


def _ground_value(value) -> tuple[bool, object]:
    from sugar_lift_py_tests.floor import NoneValue, StringValue, TermValue
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
        FalseBoolLiteralSugar,
    )
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

    if type(value) is TermValue or type(value) is StringValue:
        return True, value.value
    if type(value) is TrueBoolLiteralSugar:
        return True, True
    if type(value) is FalseBoolLiteralSugar:
        return True, False
    if type(value) is NoneValue:
        return True, None
    return False, None


def _match_ground(
    pattern: ast.pattern, subject: object, site
) -> tuple[bool, str | None]:
    if isinstance(pattern, ast.MatchValue):
        if not isinstance(pattern.value, ast.Constant):
            _unsupported_pattern(pattern, site)
        return subject == pattern.value.value, None
    if isinstance(pattern, ast.MatchSingleton):
        return subject is pattern.value, None
    if isinstance(pattern, ast.MatchOr):
        for arm in pattern.patterns:
            matched, capture = _match_ground(arm, subject, site)
            if matched:
                return True, capture
        return False, None
    if isinstance(pattern, ast.MatchAs):
        if pattern.pattern is None:
            return True, pattern.name
        matched, capture = _match_ground(pattern.pattern, subject, site)
        return matched, pattern.name if matched and pattern.name else capture
    _unsupported_pattern(pattern, site)


def _unsupported_pattern(pattern: ast.pattern, site) -> None:
    from sugar_lift_py_tests.factory import factory_panic_gap

    factory_panic_gap(
        owner="MatchSugar",
        blame=site,
        observed=type(pattern).__name__,
        requested="constructible ground match pattern",
        fix=(
            f"construct `{type(pattern).__name__}` matching from reduced pattern "
            "evidence; do not classify a ground construction gap as runtime"
        ),
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
