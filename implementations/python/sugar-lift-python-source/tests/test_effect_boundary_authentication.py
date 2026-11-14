"""Operands cannot authenticate an unconstructed callee's suppression contract."""

from types import SimpleNamespace

import pytest

from sugar_lift_py_tests.floor import BlockValue, NoneValue, ObjectValue, StringValue
from sugar_lift_py_tests.floor.object_field import ObjectField
from sugar_lift_py_tests.gap import ConstructionGap, ConstructionPanic
from sugar_lift_py_tests.outcome import ExitSet, Halted
from sugar_lift_py_tests.outcome.exit_set import true_guard
from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.temporal import builtin_name_temporal
from sugar_lift_python_source.manager_summary_derivation import (
    DerivedManagerSummaryGapV1,
    derive_manager_summary,
)
from sugar_source_tree.panic import SugarNotWritten

from frame_fresh import FRAME_FRESH


def _exception_formals():
    # These values and receiver fields used to fabricate an Expects-Raise
    # contract even if either protocol method refused to construct.
    return SimpleNamespace(
        resolved_object_cid="manager-object",
        formal_actual_values=(
            builtin_name_temporal().value_if_bound("ValueError"),
            StringValue("must escape"),
        ),
        formal_actual_bindings=(
            SimpleNamespace(coordinate=SimpleNamespace(cid="expected-formal")),
            SimpleNamespace(coordinate=SimpleNamespace(cid="match-formal")),
        ),
        receiver_state=ObjectValue(
            "Boundary",
            (ObjectField("match", NoneValue()),),
            identity="receiver",
            allocation=FRAME_FRESH,
        ),
        source_call_frame=SimpleNamespace(
            parameters=("expected", "match"),
            parameter_kinds=("positional_or_keyword", "positional_or_keyword"),
            default_sugars=(None, None),
        ),
    )


def _protocol(phase, refusal):
    def unresolved():
        if refusal == "empty-exits":
            return ExitSet(())
        if refusal == "raised-exit":
            return ExitSet(
                (
                    Halted(
                        true_guard(),
                        RaiseEffect.for_builtin("RuntimeError", blame="manager.py:1"),
                    ),
                )
            )
        if refusal == "construction-panic":
            raise ConstructionPanic(
                ConstructionGap(
                    owner="NativeManagerProtocol",
                    blame="manager.py:1",
                    observed="native call has no Python body",
                    requested="authenticated native call behavior",
                    fix="construct the native call or preserve its effect",
                )
            )
        raise SugarNotWritten(
            owner="NativeManagerProtocol",
            blame="manager.py:1",
            observed="native call has no Python body",
            requested="authenticated native call behavior",
            fix="construct the native call or preserve its effect",
        )

    def completed():
        return ExitSet.completed(BlockValue(()))

    return SimpleNamespace(
        protocol_construction_cid="constructed-protocol",
        enter_frame_cid="constructed-enter",
        exit_frame_cid="constructed-exit",
        enter_outcome=unresolved if phase == "enter" else completed,
        exit_outcome=unresolved if phase == "exit" else completed,
    )


@pytest.mark.parametrize("phase", ["enter", "exit"])
@pytest.mark.parametrize("refusal", ["empty-exits", "raised-exit"])
def test_exception_formals_do_not_seal_an_unconstructed_protocol(phase, refusal):
    summary = derive_manager_summary(
        _protocol(phase, refusal), behavior=_exception_formals()
    )
    assert isinstance(summary, DerivedManagerSummaryGapV1)
    assert summary.kind == f"{phase}-may-halt"
    assert summary.protocol_construction_cid == "constructed-protocol"
    assert summary.detail


@pytest.mark.parametrize("phase", ["enter", "exit"])
@pytest.mark.parametrize(
    ("refusal", "refused_as"),
    [("construction-panic", ConstructionPanic), ("source-gap", SugarNotWritten)],
)
def test_a_refused_protocol_phase_propagates_its_refusal(phase, refusal, refused_as):
    """A refusal constructing enter or exit leaves as itself (#7757): it is
    never turned into an ``*-may-halt`` gap, and the exception formals never
    seal a contract over it."""
    with pytest.raises(refused_as):
        derive_manager_summary(_protocol(phase, refusal), behavior=_exception_formals())


@pytest.mark.parametrize("result", [False, True, None])
def test_exception_formals_do_not_change_a_constructed_constant_exit(result):
    from sugar_lift_py_tests.context_manager_contract import (
        NeverSuppressesDispositionV1,
        ProtocolResourceSemanticsV1,
        ReturnTruthinessDispositionV1,
    )
    from sugar_lift_py_tests.floor import ReturnValue, TermValue
    from sugar_lift_python_source.manager_summary_derivation import (
        DerivedManagerSummaryV1,
    )

    protocol = SimpleNamespace(
        protocol_construction_cid="constructed-protocol",
        enter_frame_cid="constructed-enter",
        exit_frame_cid="constructed-exit",
        exit_face_id="native-exit",
        enter_outcome=lambda: ExitSet.completed(BlockValue(())),
        exit_outcome=lambda: ExitSet.completed(
            BlockValue(
                (ReturnValue(TermValue(result)),),
                can_fall_through=False,
            )
        ),
    )
    summary = derive_manager_summary(protocol, behavior=_exception_formals())
    assert isinstance(summary, DerivedManagerSummaryV1)
    assert summary.protocol_construction_cid == protocol.protocol_construction_cid
    assert summary.enter_testimony_cid == protocol.enter_frame_cid
    assert summary.exit_testimony_cid == protocol.exit_frame_cid
    assert isinstance(summary.semantics, ProtocolResourceSemanticsV1)
    disposition = summary.semantics.exit.disposition
    assert isinstance(
        disposition,
        (
            ReturnTruthinessDispositionV1
            if result is True
            else NeverSuppressesDispositionV1
        ),
    )
