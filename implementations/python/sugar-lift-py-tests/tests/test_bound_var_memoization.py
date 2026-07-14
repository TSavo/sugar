from __future__ import annotations

from types import SimpleNamespace

import pytest

from sugar_lift_py_tests.floor import BoundVar, ModuleBoundVar, TermValue
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.name_sugar import NameSugar
from sugar_lift_py_tests.temporal import TemporalContext


class CountingSource:
    def __init__(self) -> None:
        self.scopes: list[object] = []
        self.outcomes: list[Complete] = []

    def reduce(self, ctx: object) -> Complete:
        self.scopes.append(ctx)
        outcome = Complete(TermValue(len(self.scopes)))
        self.outcomes.append(outcome)
        return outcome


@pytest.mark.parametrize("binding_type", [BoundVar, ModuleBoundVar])
def test_scoped_binding_reuses_one_identical_outcome_for_every_read(
    binding_type,
) -> None:
    definition_scope = object()
    source = CountingSource()
    binding = binding_type("x", source, scope=definition_scope)
    consumer_ctx = SimpleNamespace(
        temporal=TemporalContext.empty().bind_value("x", binding)
    )
    name = NameSugar(name="x", site=object())

    first = binding.answer(consumer_ctx)
    second = binding.answer(consumer_ctx)
    binding.to_term(owner="memo law")
    binding.to_term(owner="memo law")
    consumed_first = name.desugar(consumer_ctx)
    consumed_second = name.desugar(consumer_ctx)

    assert source.scopes == [definition_scope]
    assert first is second is consumed_first is consumed_second is source.outcomes[0]


def test_scoped_binding_preserves_source_and_old_definition_scope() -> None:
    old_scope = object()
    current_scope = object()
    source = CountingSource()
    binding = BoundVar("x", source, scope=old_scope)

    assert binding.source is source
    binding.answer(current_scope)
    binding.answer(current_scope)
    assert source.scopes == [old_scope]


def test_unscoped_binding_does_not_reuse_context_dependent_outcomes() -> None:
    source = CountingSource()
    binding = BoundVar("x", source, scope=None)
    first_ctx = object()
    second_ctx = object()

    first = binding.answer(first_ctx)
    repeated = binding.answer(first_ctx)
    second = binding.answer(second_ctx)

    assert source.scopes == [first_ctx, first_ctx, second_ctx]
    assert first is not repeated
    assert repeated is not second
    assert [outcome.value.value for outcome in (first, repeated, second)] == [1, 2, 3]
