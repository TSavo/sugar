"""Naked TypeError(type(...)) must become named refusals.

A plain type dump is not a limit announcing itself — it is a missing arm
wearing instrument noise. Every site that used to raise TypeError(type(x))
must name owner, observed species, requested shape, and fix.
"""

from __future__ import annotations

from sugar_source_tree.panic import SugarNotWritten


def test_construct_binding_projection_unknown_species_is_sugar_not_written() -> None:
    from sugar_source_tree.nodes import _construct_binding_projection

    class ForeignBindingState:
        pass

    try:
        _construct_binding_projection(ForeignBindingState())
        raise AssertionError("expected SugarNotWritten")
    except SugarNotWritten as gap:
        assert "ForeignBindingState" in gap.observed
        assert gap.requested
        assert gap.fix
    except TypeError as te:
        raise AssertionError(
            f"naked TypeError is the old lie: {te!r}; want SugarNotWritten"
        ) from te


def test_manager_protocol_exit_wrong_entered_is_sugar_not_written() -> None:
    from sugar_lift_python_source.manager_protocol_construction import (
        ConstructedManagerProtocolV1,
    )

    proto = object.__new__(ConstructedManagerProtocolV1)
    object.__setattr__(proto, "exit_face_id", "exit-face:test")
    try:
        proto.exit_outcome_for(object())
        raise AssertionError("expected SugarNotWritten")
    except SugarNotWritten as gap:
        assert "EnteredManagerStateValue" in gap.observed
        assert "TypeError" in gap.fix or "enter" in gap.fix.lower()
    except TypeError as te:
        raise AssertionError(
            f"naked TypeError is the old lie: {te!r}; want SugarNotWritten"
        ) from te


def test_generator_exit_wrong_entered_is_sugar_not_written() -> None:
    from sugar_lift_python_source.manager_protocol_construction import (
        exit_generator_resource_outcome_for,
    )

    class _Protocol:
        exit_face_id = "exit-face:gen"
        protocol_construction_cid = "blake3-512:" + ("11" * 32)

    try:
        exit_generator_resource_outcome_for(_Protocol(), object())
        raise AssertionError("expected SugarNotWritten")
    except SugarNotWritten as gap:
        assert "EnteredGeneratorManagerStateV1" in gap.observed
        assert gap.fix
    except TypeError as te:
        raise AssertionError(
            f"naked TypeError is the old lie: {te!r}; want SugarNotWritten"
        ) from te


def test_receiver_partition_unknown_face_is_construction_panic() -> None:
    from sugar_lift_py_tests.floor.receiver_state_partition_value import (
        ReceiverStatePartitionValue,
    )
    from sugar_lift_py_tests.gap.panic import ConstructionPanic
    from sugar_lift_py_tests.outcome import ExitSet

    class ForeignFace:
        guard = None

    partition = ReceiverStatePartitionValue(exits=ExitSet((ForeignFace(),)))
    try:
        partition.to_term(owner="test")
        raise AssertionError("expected ConstructionPanic")
    except ConstructionPanic as panic:
        assert "ForeignFace" in panic.info.observed
        assert "Completed" in panic.info.requested or "Halted" in panic.info.requested
    except TypeError as te:
        raise AssertionError(
            f"naked TypeError is the old lie: {te!r}; want ConstructionPanic"
        ) from te
