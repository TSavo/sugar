"""A producer-retained source completion is single-publication testimony."""

from __future__ import annotations

from dataclasses import dataclass, replace

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import CallSiteValue, FloorValue, TermValue
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.ir import ctor
from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet, true_guard
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
from sugar_lift_py_tests.sugar_body import SugarBody
from sugar_source_tree.panic import BackendDefect, SugarNotWritten


@dataclass
class _CountingCompletion(ConstructedTermSugar):
    value: FloorValue
    reductions: int = 0

    @classmethod
    def witnesses(cls):
        return None

    def desugar(self, ctx=None):
        del ctx
        self.reductions += 1
        return Complete(self.value)

    def to_term(self, *, owner: str):
        del owner
        return ctor("test:retained-source-body", ())


def _retained_source_call(original: FloorValue | None = None):
    original = TermValue(7) if original is None else original
    body = _CountingCompletion(original)
    source_call = CallSiteValue(
        target_name="source_value",
        arg_values=(),
        parameters=(),
        term=ctor("call:source_value", ()),
        body=SugarBody(body, SugarRole.CONTROL_FLOW_BODY),
        site="source.py:4:11",
        source_call_frame_cid="blake3-512:" + "7" * 128,
    )
    produced = source_call.producer_outcome(None)
    assert isinstance(produced, Complete)
    retained = produced.value
    assert isinstance(retained, CallSiteValue)
    assert retained is not source_call
    assert body.reductions == 1
    return retained, body, original


@pytest.mark.parametrize(
    ("replay_kind", "replacement_value"),
    (
        ("complete", 7),
        ("complete", 9),
        ("exitset", 7),
        ("exitset", 9),
    ),
)
def test_retained_source_completion_refuses_different_producer_replay(
    replay_kind: str,
    replacement_value: int,
) -> None:
    """Lying twin: even equal completion replay cannot republish testimony."""
    retained, body, original = _retained_source_call()
    retained_testimony = retained._retained_source_completion
    identity_before = retained._identity()
    hash_before = hash(retained)
    replacement = original if replacement_value == 7 else TermValue(replacement_value)
    replay = (
        Complete(replacement)
        if replay_kind == "complete"
        else ExitSet((Completed(true_guard(), replacement),))
    )

    with pytest.raises(BackendDefect, match="retained|replay|producer"):
        retained.project_producer_outcome(replay)

    assert body.reductions == 1
    assert retained._retained_source_completion is retained_testimony
    assert retained._identity() == identity_before
    assert hash(retained) == hash_before
    projected = retained.project_operation_receiver_outcome(
        None, owner="CallSiteSugar positional actual"
    )
    assert isinstance(projected, Complete)
    assert projected.value is original


@pytest.mark.parametrize("door", ("producer_outcome", "reduce_source_outcome"))
def test_retained_source_completion_refuses_every_second_reduction_door(
    door: str,
) -> None:
    """A retained wrapper is a consumer value, never a second producer handle."""
    retained, body, original = _retained_source_call()
    testimony = retained._retained_source_completion
    identity_before = retained._identity()

    with pytest.raises(BackendDefect, match="retained|replay|producer"):
        getattr(retained, door)(None)

    assert body.reductions == 1
    assert retained._retained_source_completion is testimony
    assert retained._identity() == identity_before
    projected = retained.project_operation_receiver_outcome(
        None, owner="CallSiteSugar positional actual"
    )
    assert isinstance(projected, Complete)
    assert projected.value is original


def test_legacy_operation_projection_paths_consume_retained_value_without_reduction() -> (
    None
):
    """Legacy callers read the seat; neither path may re-enter the source body."""
    retained, body, original = _retained_source_call()

    projected = retained.project_operation_receiver(
        None, owner="legacy operation actual"
    )
    dug = retained._dig_floor_or_none(None, owner="legacy force floor")

    assert projected is original
    assert dug is original
    assert body.reductions == 1


def test_retained_force_floor_consumes_testimony_without_second_reduction() -> None:
    """force_floor is a retained-value consumer after producer publication."""
    retained, body, original = _retained_source_call()

    projected = retained.force_floor(None, owner="retained force floor")

    assert projected is original
    assert body.reductions == 1


def test_retained_nested_callsite_preserves_existing_recursion_refusal() -> None:
    """A retained nested call is recursively forced, never returned as opaque."""
    nested = CallSiteValue(
        target_name="source_value",
        arg_values=(),
        parameters=(),
        term=ctor("call:source_value", ()),
        body=None,
    )
    retained, body, _ = _retained_source_call(nested)

    with pytest.raises(ConstructionPanic, match="recursive callsite value demand"):
        retained.force_floor(None, owner="retained nested force floor")

    assert body.reductions == 1


def test_malformed_non_none_retention_is_exact_type_loud() -> None:
    """A non-None lookalike cannot satisfy the private retention consumer."""
    retained, body, _ = _retained_source_call()
    malformed = replace(retained)
    object.__setattr__(malformed, "_retained_source_completion", object())

    with pytest.raises(BackendDefect, match="retained|producer"):
        malformed.project_operation_receiver_outcome(
            None, owner="CallSiteSugar positional actual"
        )
    with pytest.raises(BackendDefect, match="retained|producer"):
        malformed.project_operation_receiver(None, owner="legacy operation actual")
    with pytest.raises(BackendDefect, match="retained|producer"):
        malformed._dig_floor_or_none(None, owner="legacy force floor")
    with pytest.raises(BackendDefect, match="retained|producer"):
        malformed.force_floor(None, owner="retained force floor")
    assert body.reductions == 1


def test_absent_retention_after_dataclass_replace_is_the_only_sugar_gap() -> None:
    """An ordinary remint drops init-closed testimony and stays typed absent."""
    retained, body, _ = _retained_source_call()
    absent = replace(retained)
    assert absent._retained_source_completion is None

    with pytest.raises(SugarNotWritten, match="retained|producer"):
        absent.project_operation_receiver_outcome(
            None, owner="CallSiteSugar positional actual"
        )
    assert body.reductions == 1


def test_non_floor_completion_is_a_producer_defect() -> None:
    """Producer publication accepts only the exact completed Floor codomain."""
    original = TermValue(7)
    body = _CountingCompletion(original)
    source_call = CallSiteValue(
        target_name="source_value",
        arg_values=(),
        parameters=(),
        term=ctor("call:source_value", ()),
        body=SugarBody(body, SugarRole.CONTROL_FLOW_BODY),
        site="source.py:4:11",
    )

    with pytest.raises(BackendDefect, match="Floor|completion|producer"):
        source_call.project_producer_outcome(Complete(object()))
    assert body.reductions == 0


def test_retention_wrapper_with_non_floor_value_is_backend_defect() -> None:
    """The private wrapper type alone cannot authorize an invalid codomain."""
    retained, body, _ = _retained_source_call()
    testimony = retained._retained_source_completion
    object.__setattr__(testimony, "value", object())

    with pytest.raises(BackendDefect, match="Floor|completion|retained"):
        retained.project_operation_receiver_outcome(
            None, owner="CallSiteSugar positional actual"
        )
    assert body.reductions == 1


def test_retained_completion_consumer_requires_the_private_exact_wrapper() -> None:
    """The public call carries testimony, but only its private type is consumed."""
    retained, body, original = _retained_source_call()
    testimony = retained._retained_source_completion
    assert testimony is not None
    assert type(testimony).__module__ == CallSiteValue.__module__
    assert body.reductions == 1

    projected = retained.project_operation_receiver_outcome(
        None, owner="CallSiteSugar keyword actual"
    )

    assert isinstance(projected, Complete)
    assert projected.value is original
    assert body.reductions == 1
