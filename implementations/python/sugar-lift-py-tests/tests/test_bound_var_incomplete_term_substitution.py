"""Incomplete BoundVar term substitution is a structured FactoryPanic (#5304).

A BoundVar whose source answers Incomplete (e.g. SequenceRepetitionRuntimeEffect
from list/tuple * len(...)/symbolic count) lawfully keeps that typed effect at
the producer. Asking BoundVar.to_term to collapse the incomplete effect into a
completed call argument is a missing Floor projection recognizer and must panic
with grounds — never a bare RuntimeError from complete_value.
"""

from __future__ import annotations

import ast

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext, ReduceContext
from sugar_lift_py_tests.effect import SequenceRepetitionRuntimeEffect
from sugar_lift_py_tests.factory import FactoryPanic, GapKind, GapLocus
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.floor import BoundVar, SymbolicValue
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.outcome import Incomplete
from sugar_lift_py_tests.temporal import TemporalContext


def _sequence_repetition_body(*, count_name: str = "count"):
    temporal = TemporalContext.empty().bind_value(
        count_name, SymbolicValue(make_var(count_name))
    )
    build_ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    body = build_ctx.build_body(
        ast.parse(f"[1] * {count_name}", mode="eval").body,
        SugarRole.TERM,
    )
    scope = ReduceContext(temporal=temporal)
    return body, scope


def test_bound_source_answers_typed_sequence_repetition_effect() -> None:
    body, scope = _sequence_repetition_body()
    binding = BoundVar("pad", body, scope=scope)

    outcome = binding.answer()

    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, SequenceRepetitionRuntimeEffect)
    assert "sequence repetition" in outcome.reason


def test_incomplete_bound_var_to_term_is_structured_factory_panic() -> None:
    body, scope = _sequence_repetition_body()
    binding = BoundVar("pad", body, scope=scope)

    with pytest.raises(FactoryPanic) as raised:
        binding.to_term(owner="callsite-arg")

    panic = raised.value
    assert isinstance(panic, BaseException)
    assert not isinstance(panic, Exception)
    assert panic.info.gap_kind is GapKind.FLOOR
    assert panic.info.gap_locus is GapLocus.PROJECTION
    assert panic.info.owner == "callsite-arg"
    assert panic.info.blame == "pad"
    assert panic.info.observed == "SequenceRepetitionRuntimeEffect"
    assert panic.info.requested == "completed BoundVar term substitution"
    assert "never read an incomplete effect" in panic.info.fix
    assert "RuntimeError" not in type(panic).__name__


def test_incomplete_bound_var_to_term_does_not_raise_bare_runtime_error() -> None:
    body, scope = _sequence_repetition_body()
    binding = BoundVar("pad", body, scope=scope)

    with pytest.raises(FactoryPanic):
        binding.to_term(owner="excel pad width")
