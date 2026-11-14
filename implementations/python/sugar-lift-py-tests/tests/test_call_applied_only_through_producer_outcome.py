"""A function body is applied only through ``CallSiteValue.producer_outcome``.

#7757: a floor demand on a call no producer has applied yet
(``_dig_floor_or_none``, ``force_floor``) applies it through the one
application and reads the completed face back; ``CallSiteSugar`` never
projects a frame's deferred native operation or the callee's universe beside
it.  Every halt stays, as the Call's own.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context_manager_resolution import (
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import CallSiteValue, FloorValue, TermValue
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.ir import ctor
from sugar_lift_py_tests.outcome import ExitSet, Halted, true_guard
from sugar_lift_py_tests.sugar.call_site_sugar import CallSiteSugar
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
from sugar_lift_py_tests.sugar_body import SugarBody
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Call, FunctionDef
from sugar_source_tree.tree import SourceFile


@dataclass
class _CountingBody(ConstructedTermSugar):
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
        return ctor("test:applied-body", ())


def _unapplied_call(outcome: ExitSet):
    body = _CountingBody(outcome)
    callsite = CallSiteValue(
        target_name="source_value",
        arg_values=(),
        parameters=(),
        term=ctor("call:source_value", ()),
        body=SugarBody(body, SugarRole.CONTROL_FLOW_BODY),
        site="source.py:4:11",
        source_call_frame_cid="blake3-512:" + "7" * 128,
    )
    assert callsite._retained_source_completion is None
    return callsite, body


def _halt() -> Halted:
    return Halted(
        true_guard(),
        RaiseEffect.for_builtin("ValueError", occurrence="source.py:2:4"),
        TermValue(0),
    )


@pytest.fixture
def applications(monkeypatch: pytest.MonkeyPatch) -> list[CallSiteValue]:
    """Every call ``producer_outcome`` applies, in order."""
    applied: list[CallSiteValue] = []
    original = CallSiteValue.producer_outcome

    def counting(self, ctx=None):
        applied.append(self)
        return original(self, ctx)

    monkeypatch.setattr(CallSiteValue, "producer_outcome", counting)
    return applied


# ---------------------------------------------------------------------------
# CallSiteValue._dig_floor_or_none
# ---------------------------------------------------------------------------


def test_dig_applies_an_unapplied_call_through_producer_outcome(applications) -> None:
    """Truth: the dug floor is the body's completion, applied once, by the one door."""
    original = TermValue(7)
    callsite, body = _unapplied_call(ExitSet.completed(original))

    dug = callsite._dig_floor_or_none(None, owner="dig through producer")

    assert dug == original
    assert body.reductions == 1
    assert applications == [callsite]


def test_dig_keeps_a_halting_body_as_the_call_s_own_halt(applications) -> None:
    """Lying twin: an all-halt body yields no floor; its halt is the Call's."""
    callsite, body = _unapplied_call(ExitSet((_halt(),)))
    incomplete: list = []

    dug = callsite._dig_floor_or_none(
        None, owner="halting dig", incomplete_outcome=incomplete
    )

    assert dug is None
    assert body.reductions == 1
    assert applications == [callsite]
    (outcome,) = incomplete
    assert outcome.halts() == outcome.exits
    (halt,) = outcome.halts()
    assert isinstance(halt.effect, RaiseEffect)
    assert halt.effect.producer_node_owner == "Call"


# ---------------------------------------------------------------------------
# CallSiteValue.force_floor
# ---------------------------------------------------------------------------


def test_force_floor_applies_an_unapplied_call_through_producer_outcome(
    applications,
) -> None:
    """Truth: the forced floor is the body's completion, applied by the one door."""
    original = TermValue(9)
    callsite, body = _unapplied_call(ExitSet.completed(original))

    forced = callsite.force_floor(None, owner="force through producer")

    assert forced == original
    assert body.reductions == 1
    assert applications == [callsite]


def test_force_floor_still_refuses_a_body_whose_every_arm_halts(applications) -> None:
    """Lying twin: the halt is never dropped into an invented floor."""
    callsite, body = _unapplied_call(ExitSet((_halt(),)))

    with pytest.raises(ConstructionPanic, match="every arm halts"):
        callsite.force_floor(None, owner="halting force")

    assert body.reductions == 1
    assert applications == [callsite]


def test_retained_completion_is_read_back_never_applied_again(applications) -> None:
    """A producer-applied call is read through its seat by both floor demands."""
    original = TermValue(5)
    callsite, body = _unapplied_call(ExitSet.completed(original))
    retained = callsite.producer_outcome(None).completed_value()
    assert isinstance(retained, CallSiteValue)

    assert retained._dig_floor_or_none(None, owner="retained dig") == original
    assert retained.force_floor(None, owner="retained force") == original
    assert body.reductions == 1
    assert applications == [callsite]


# ---------------------------------------------------------------------------
# CallSiteSugar.desugar
# ---------------------------------------------------------------------------


@dataclass
class _CountingUniverse:
    """A callee universe that records being reduced at a call."""

    reductions: int = 0

    def desugar(self, ctx=None):
        del ctx
        self.reductions += 1
        return ExitSet.completed(TermValue(13))


class _Site:
    """A fragment's two coordinates: its unit's source CID and its span."""

    class _Span:
        start_line, start_col, end_line, end_col = 3, 0, 3, 9

    source_cid = "blake3-512:" + "c" * 128
    line_col_span = _Span()


def test_call_without_a_frame_never_reduces_the_callee_universe(applications) -> None:
    """A call carrying the callee's universe but no frame applies no body.

    The universe is never reduced beside it.  With no body applied and no
    builtin binding, nothing answers the call: it is the one unanswered
    citation, completing only under its atom and otherwise raising something
    undetermined (#7757: a halt is never dropped), never a total completion.
    """
    universe = _CountingUniverse()

    outcome = CallSiteSugar(
        target_name="consume",
        args=(),
        site=_Site(),
        formal_function_sugar=universe,
    ).desugar(None)

    assert universe.reductions == 0
    assert applications == []
    assert outcome.completed_value() is None
    (halt,) = outcome.halts()
    assert isinstance(halt.effect, UndeterminedRaiseEffect)
    assert halt.effect.producer_node_owner == "UnknownCallee:consume"


def _source_coordinate(node) -> SourceFragmentCoordinateV1:
    span = node.line_col_span()
    return SourceFragmentCoordinateV1(
        node.unit.source_cid,
        span.start_line,
        span.start_col,
        span.end_line,
        span.end_col,
    )


def test_frame_native_operation_is_applied_by_producer_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A frame carrying a deferred native operation is applied by the one door.

    The call never discharges the frame's pending operation itself; its body
    is applied by ``producer_outcome``, which discharges any deferred
    operation against the bound actuals.
    """
    source = "def helper(left, right=2):\n    return left + right\n\nhelper(1, 2)\n"
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (source, "native_applied.py", blake3_512_of(source.encode())),
        construction_context=context,
    )
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    call = next(
        node
        for node in tree.nodes()
        if isinstance(node, Call) and getattr(node.func, "id", None) == "helper"
    )
    context.source_call_frames[_source_coordinate(call)] = (
        function.source_visible_call_frame()
    )
    sugar = call.sugar()
    assert isinstance(sugar, CallSiteSugar)
    assert sugar.source_call_frame is not None
    native_frame = sugar.source_call_frame.with_native_operation_projection(
        function.formal_coordinates(), function.sugar().desugar(None)
    )
    assert native_frame.pending_native_operation is not None
    seated = replace(sugar, source_call_frame=native_frame)

    applied: list[CallSiteValue] = []
    marker: FloorValue = TermValue(41)

    def producer(self, ctx=None):
        del ctx
        applied.append(self)
        return ExitSet.completed(marker)

    monkeypatch.setattr(CallSiteValue, "producer_outcome", producer)

    outcome = seated.desugar(None)

    assert len(applied) == 1
    assert applied[0].body is not None
    assert outcome.completed_value() == marker
