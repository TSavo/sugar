"""A source-call positional actual sequences its retained producer outcome once."""

from __future__ import annotations

from dataclasses import dataclass, fields, replace

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import (
    BlockValue,
    CallSiteValue,
    ComprehensionValue,
    ReturnValue,
    TermValue,
)
from sugar_lift_py_tests.ir import atomic, ctor
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_py_tests.outcome.exit_set import partition
from sugar_lift_py_tests.sugar.call_site_sugar import CallSiteSugar
from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
from sugar_lift_py_tests.sugar_body import SugarBody
from sugar_source_tree.nodes import LanguageCallee
from sugar_source_tree.panic import SugarNotWritten


class _Site:
    """A fragment's two coordinates: its unit's source CID and its span."""

    class _Span:
        start_line, start_col, end_line, end_col = 10, 11, 10, 24

    source_cid = "blake3-512:" + "a" * 128
    line_col_span = _Span()


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
                _ReducedBlock((TermValue(11),), True, ()),
                frozenset({left_face}),
            ),
            Halted(
                right_guard,
                RaiseEffect.for_builtin("ValueError", occurrence="source.py:5:8"),
                _ReducedBlock((TermValue(22),), True, ()),
                frozenset({right_face}),
            ),
            Completed(
                completed_guard,
                block,
                frozenset({completed_face}),
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
    assert outcome.completed_value() is not None
    assert outcome.completed_value() is callsite


def test_ordinary_floor_operation_actual_projection_is_identity() -> None:
    """The new outcome protocol does not perturb ordinary concrete Floors."""
    value = TermValue(7)
    outcome = value.project_operation_receiver_outcome(
        None, owner="CallSiteSugar positional actual"
    )
    assert outcome.completed_value() is not None
    assert outcome.completed_value() is value


