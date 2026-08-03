"""A source-call positional actual sequences its retained producer outcome once."""

from __future__ import annotations

from dataclasses import dataclass, fields, replace

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.floor import (
    BlockValue,
    CallSiteValue,
    ComprehensionValue,
    ReturnValue,
    TermValue,
)
from sugar_lift_py_tests.ir import atomic, ctor
from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet, Halted
from sugar_lift_py_tests.outcome.exit_set import partition
from sugar_lift_py_tests.sugar.call_site_sugar import CallSiteSugar
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
from sugar_lift_py_tests.sugar_body import SugarBody
from sugar_source_tree.panic import SugarNotWritten


@dataclass(frozen=True)
class _Pending:
    candidate_cid: str
    demands: tuple = ()


@dataclass
class _CountingSourceBody(ConstructedTermSugar):
    outcome: ExitSet
    reductions: int = 0

    @classmethod
    def witnesses(cls):
        return None

    def desugar(self, ctx=None):
        del ctx
        self.reductions += 1
        return self.outcome

    def to_term(self, *, owner: str):
        del owner
        return ctor("test:source-body", ())


@dataclass(frozen=True)
class _ProducedCallArgument(ConstructedTermSugar):
    outcome: ExitSet
    term: object

    @classmethod
    def witnesses(cls):
        return None

    def desugar(self, ctx=None):
        del ctx
        return self.outcome

    def to_term(self, *, owner: str):
        del owner
        return self.term


def _source_call_partition(result_coordinate: str = "py.listcomp"):
    comprehension = ComprehensionValue(ctor(result_coordinate, ()))
    block = BlockValue(
        (ReturnValue(comprehension),),
        fall_through=(),
        can_fall_through=False,
    )
    left_guard = atomic("test:left", [])
    right_guard = atomic("test:right", [])
    completed_guard = atomic("test:completed", [])
    left_face = partition("left-raise")[0]
    right_face = partition("right-raise")[1]
    completed_face = partition("completed-return")[0]
    source = ExitSet(
        (
            Halted(
                left_guard,
                RaiseEffect.for_builtin("TypeError", occurrence="source.py:3:8"),
                TermValue(11),
                frozenset({left_face}),
                (_Pending("pending:left"),),
            ),
            Halted(
                right_guard,
                RaiseEffect.for_builtin("ValueError", occurrence="source.py:5:8"),
                TermValue(22),
                frozenset({right_face}),
                (_Pending("pending:right"),),
            ),
            Completed(
                completed_guard,
                block,
                frozenset({completed_face}),
                (_Pending("pending:completed"),),
            ),
        )
    )
    body = _CountingSourceBody(source)
    callsite = CallSiteValue(
        target_name="source_values",
        arg_values=(),
        parameters=(),
        term=ctor("call:source_values", ()),
        body=SugarBody(body, SugarRole.CONTROL_FLOW_BODY),
        site="consumer.py:1:4",
        source_call_frame_cid="blake3-512:" + "1" * 128,
    )
    return callsite, body, comprehension


def test_outer_call_sequences_retained_three_arm_source_actual_once() -> None:
    """Truth: halts bypass collection; only the retained return keeps going."""
    inner, body, returned = _source_call_partition()
    produced = inner.producer_outcome(None)
    assert body.reductions == 1
    assert isinstance(produced, ExitSet)
    produced_halts = tuple(face for face in produced.exits if isinstance(face, Halted))
    produced_completed = tuple(
        face for face in produced.exits if isinstance(face, Completed)
    )
    assert len(produced_halts) == 2
    assert len(produced_completed) == 1
    assert isinstance(produced_completed[0].value, CallSiteValue)
    assert produced_completed[0].value is not inner

    outer = CallSiteSugar(
        target_name="len",
        args=(_ProducedCallArgument(produced, inner.term),),
        site="consumer.py:9:11",
    ).desugar(None)

    assert body.reductions == 1
    assert isinstance(outer, ExitSet)
    outer_halts = tuple(face for face in outer.exits if isinstance(face, Halted))
    assert len(outer_halts) == 2
    assert all(after is before for after, before in zip(outer_halts, produced_halts))
    outer_completed = tuple(face for face in outer.exits if isinstance(face, Completed))
    assert len(outer_completed) == 1
    assert outer_completed[0].guard == produced_completed[0].guard
    assert outer_completed[0].faces == produced_completed[0].faces
    assert (
        outer_completed[0].pending_contracts == produced_completed[0].pending_contracts
    )
    projected_call = outer_completed[0].value
    assert isinstance(projected_call, CallSiteValue)
    assert projected_call.target_name == "len"
    assert projected_call.arg_values == (returned,)


def test_outer_call_sequences_retained_keyword_source_actual_symmetrically() -> None:
    """Keyword twin: preserve its name while only the completed Floor advances."""
    inner, body, returned = _source_call_partition()
    produced = inner.producer_outcome(None)
    assert body.reductions == 1
    produced_halts = tuple(face for face in produced.exits if isinstance(face, Halted))
    produced_completed = next(
        face for face in produced.exits if isinstance(face, Completed)
    )

    outer = CallSiteSugar(
        target_name="consume",
        args=(),
        keywords=(("value", _ProducedCallArgument(produced, inner.term)),),
        site="consumer.py:10:11",
    ).desugar(None)

    assert body.reductions == 1
    assert isinstance(outer, ExitSet)
    outer_halts = tuple(face for face in outer.exits if isinstance(face, Halted))
    assert len(outer_halts) == 2
    assert all(after is before for after, before in zip(outer_halts, produced_halts))
    completed = next(face for face in outer.exits if isinstance(face, Completed))
    assert completed.guard == produced_completed.guard
    assert completed.faces == produced_completed.faces
    assert completed.pending_contracts == produced_completed.pending_contracts
    projected_call = completed.value
    assert isinstance(projected_call, CallSiteValue)
    assert projected_call.target_name == "consume"
    assert projected_call.keyword_names == ("value",)
    assert projected_call.arg_values == (returned,)


def test_body_bearing_call_without_retained_completion_stays_loud() -> None:
    """Lying twin: a consumer cannot trigger a second source-body reduction."""
    callsite, body, _ = _source_call_partition()
    with pytest.raises(SugarNotWritten, match="retained|producer"):
        callsite.project_operation_receiver_outcome(
            None, owner="CallSiteSugar positional actual"
        )
    assert body.reductions == 0


def test_bodyless_operation_actual_projection_is_identity() -> None:
    """Ordinary Floor default: an opaque bodyless call remains its own receiver."""
    callsite = CallSiteValue(
        target_name="opaque",
        arg_values=(),
        parameters=(),
        term=ctor("call:opaque", ()),
        body=None,
    )
    outcome = callsite.project_operation_receiver_outcome(
        None, owner="CallSiteSugar positional actual"
    )
    assert isinstance(outcome, Complete)
    assert outcome.value is callsite


def test_ordinary_floor_operation_actual_projection_is_identity() -> None:
    """The new outcome protocol does not perturb ordinary concrete Floors."""
    value = TermValue(7)
    outcome = value.project_operation_receiver_outcome(
        None, owner="CallSiteSugar positional actual"
    )
    assert isinstance(outcome, Complete)
    assert outcome.value is value


def test_retained_source_completion_is_private_and_remint_closed() -> None:
    """Lying twins: constructor and foreign dataclass remints gain no retention."""
    retained = next(
        item
        for item in fields(CallSiteValue)
        if item.name == "_retained_source_completion"
    )
    assert retained.init is False
    inner, body, _ = _source_call_partition()
    produced = inner.producer_outcome(None)
    completed_call = next(
        face.value for face in produced.exits if isinstance(face, Completed)
    )
    assert body.reductions == 1
    reminted = replace(completed_call)
    foreign = replace(completed_call, target_name="foreign")
    for candidate in (reminted, foreign):
        with pytest.raises(SugarNotWritten, match="retained|producer"):
            candidate.project_operation_receiver_outcome(
                None, owner="CallSiteSugar positional actual"
            )
    assert body.reductions == 1


def test_retained_completion_participates_in_exact_wrapper_identity() -> None:
    """Distinct returns at one call coordinate remain distinct destinations."""
    left, left_body, _ = _source_call_partition("py.listcomp:left")
    right, right_body, _ = _source_call_partition("py.listcomp:right")
    left_wrapper = next(
        face.value
        for face in left.producer_outcome(None).exits
        if isinstance(face, Completed)
    )
    right_wrapper = next(
        face.value
        for face in right.producer_outcome(None).exits
        if isinstance(face, Completed)
    )
    assert left_body.reductions == right_body.reductions == 1
    assert left.term == right.term
    assert left_wrapper != right_wrapper
    assert hash(left_wrapper) == hash(left_wrapper)
    assert hash(right_wrapper) == hash(right_wrapper)
    distinct = ExitSet(
        (
            Completed(atomic("test:identity-left", []), left_wrapper),
            Completed(atomic("test:identity-right", []), right_wrapper),
        )
    ).normalize()
    assert len(distinct.exits) == 2

    same_a, same_a_body, _ = _source_call_partition("py.listcomp:same")
    same_b, same_b_body, _ = _source_call_partition("py.listcomp:same")
    same_a_wrapper = next(
        face.value
        for face in same_a.producer_outcome(None).exits
        if isinstance(face, Completed)
    )
    same_b_wrapper = next(
        face.value
        for face in same_b.producer_outcome(None).exits
        if isinstance(face, Completed)
    )
    assert same_a_body.reductions == same_b_body.reductions == 1
    assert same_a_wrapper == same_b_wrapper
    assert hash(same_a_wrapper) == hash(same_b_wrapper)
    merged = ExitSet(
        (
            Completed(atomic("test:identity-a", []), same_a_wrapper),
            Completed(atomic("test:identity-b", []), same_b_wrapper),
        )
    ).normalize()
    assert len(merged.exits) == 1


def test_identity_memo_starts_only_after_producer_seats_retained_wrapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No pre-publication hash can cache the unretained source call identity."""
    from sugar_lift_py_tests.floor import call_site_value as callsite_module

    monkeypatch.setattr(callsite_module, "_CALLSITE_COORDINATE", {})
    inner, body, _ = _source_call_partition()
    assert callsite_module._callsite_coordinate_memo_size() == 0

    produced = inner.producer_outcome(None)

    assert body.reductions == 1
    wrapper = next(face.value for face in produced.exits if isinstance(face, Completed))
    assert wrapper is not inner
    assert callsite_module._callsite_coordinate_memo_size() == 1
    first_hash = hash(wrapper)
    assert hash(wrapper) == first_hash
    assert callsite_module._callsite_coordinate_memo_size() == 1
