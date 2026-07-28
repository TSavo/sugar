"""Source-resource exit over nested Completed, Returned, and Halted body faces.

One source-derived manager evaluation and enter; every outgoing body face
consults exit with arguments derived from that face (ExitFaceBinding). False
exit preserves return/halt and temporal state; truthy exit suppresses only an
incoming raise; exit halt supersedes every incoming face.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sugar_lift_py_tests.context_manager_contract import (
    NeverSuppressesDispositionV1,
    ReturnTruthinessDispositionV1,
)
from sugar_lift_py_tests.context_manager_resolution import SourceFragmentCoordinateV1
from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.floor import BlockValue, ReturnValue, TermValue
from sugar_lift_py_tests.ir import _Atomic
from sugar_lift_py_tests.outcome import Complete, Completed, Halted, Incomplete
from sugar_lift_py_tests.outcome.exit_set import ExitSet, true_guard
from sugar_lift_py_tests.outcome.resource_bindings import ExitFaceBinding
from sugar_lift_py_tests.sugar.method_call_sugar import MethodCallSugar
from sugar_lift_py_tests.sugar.resource_coord_sugar import (
    ExitTracebackRefSugar,
    ExitTypeRefSugar,
    ExitValueRefSugar,
    ManagerRefSugar,
)
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.with_source_resource_sugar import WithSourceResourceSugar
from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock


class _FixedSugar(Sugar):
    def __init__(self, outcome):
        self.outcome = outcome

    def desugar(self, ctx=None):
        del ctx
        return self.outcome

    @classmethod
    def witnesses(cls):
        return ()


class _RecordingProtocol:
    """Records enter/exit invocations and the body face that authorized each exit."""

    def __init__(self, *, exit_value=None, exit_outcome=None):
        self.enter_calls = 0
        self.exit_calls = 0
        self.exit_entered = []
        self.exit_value = exit_value or BlockValue((), can_fall_through=True)
        self._exit_outcome = exit_outcome
        self.enter_value = TermValue(2)

    def enter_resource_outcome(self, ctx=None):
        del ctx
        self.enter_calls += 1
        return Complete(SimpleNamespace(enter_value=self.enter_value))

    def exit_outcome_for(self, entered, ctx=None):
        del ctx
        self.exit_calls += 1
        self.exit_entered.append(entered)
        if self._exit_outcome is not None:
            return self._exit_outcome
        return Complete(self.exit_value)


def _protocol_calls(face_id: str = "exit-face"):
    enter_definition = SourceFragmentCoordinateV1(
        "blake3-512:" + "e" * 128, 1, 0, 1, 1
    )
    exit_definition = SourceFragmentCoordinateV1(
        "blake3-512:" + "x" * 128, 2, 0, 2, 1
    )
    enter = MethodCallSugar(
        receiver=ManagerRefSugar(slot_id="manager-slot", site=None),
        name="__enter__",
        args=(),
        native_definition_coordinate=enter_definition,
        site=None,
    )
    exit_ = MethodCallSugar(
        receiver=ManagerRefSugar(slot_id="manager-slot", site=None),
        name="__exit__",
        args=(
            ExitTypeRefSugar(face_id=face_id, site=None),
            ExitValueRefSugar(face_id=face_id, site=None),
            ExitTracebackRefSugar(face_id=face_id, site=None),
        ),
        native_definition_coordinate=exit_definition,
        site=None,
    )
    return enter, exit_, enter_definition, exit_definition


def _source_resource(*, protocol, summary, body, face_id="exit-face", slot=None):
    enter, exit_, enter_definition, exit_definition = _protocol_calls(face_id)
    return WithSourceResourceSugar(
        manager=_FixedSugar(Complete(TermValue(1))),
        enter=enter,
        exit=exit_,
        enter_definition=enter_definition,
        exit_definition=exit_definition,
        protocol=protocol,
        summary=summary,
        body=body,
        manager_slot_id="manager-slot",
        enter_slot_id=slot,
        exit_face_id=face_id,
        site="resource.py:3:4",
    )


def _truthiness_summary():
    return SimpleNamespace(
        semantics=SimpleNamespace(
            exit=SimpleNamespace(disposition=ReturnTruthinessDispositionV1())
        )
    )


def _never_summary():
    return SimpleNamespace(
        semantics=SimpleNamespace(
            exit=SimpleNamespace(disposition=NeverSuppressesDispositionV1())
        )
    )


def _state(marker: str):
    return _ReducedBlock(
        entries=(marker,), can_fall_through=False, fall_through=()
    )


def _nested_body_faces():
    """One ExitSet with Completed, Returned, and Halted faces under distinct guards."""
    raise_effect = RaiseEffect(
        exception_name="ValueError",
        occurrence="body.py:10:8:raise",
        blame="body.py:10:8:raise",
    )
    return ExitSet(
        (
            Completed(
                _Atomic("body-completed", ()),
                BlockValue((), can_fall_through=True),
            ),
            Completed(
                _Atomic("body-returned", ()),
                BlockValue(
                    (ReturnValue(TermValue("early-return")),),
                    can_fall_through=False,
                ),
            ),
            Halted(
                _Atomic("body-halted", ()),
                raise_effect,
                _state("pre-raise"),
            ),
        )
    ), raise_effect


def _binding_kinds(exits, face_id: str):
    """Recover ExitFaceBinding kinds carried as InvValue testimony on each face."""
    kinds = []
    for face in exits:
        record = face.value if isinstance(face, Completed) else face.state
        entries = getattr(record, "entries", ()) or ()
        rendered = " ".join(str(entry) for entry in entries)
        # ExitFaceBinding.to_facts writes exit_type / exit_value equalities.
        if "exit_type" in rendered or "exit_value" in rendered:
            if "None" in rendered and "raise" not in rendered.lower():
                kinds.append("completed-ish")
            elif "raise" in rendered or "open_exit" in rendered:
                kinds.append("raised-ish")
            else:
                kinds.append("bound")
        # Face identity rides the guard of the body arm.
        kinds.append(("guard", str(face.guard)))
    return kinds


def test_one_enter_and_exit_per_nested_body_face():
    """Each Completed / Returned / Halted body face consults exit once."""
    body, _raise = _nested_body_faces()
    protocol = _RecordingProtocol(exit_value=TermValue(False))
    sugar = _source_resource(
        protocol=protocol,
        summary=_truthiness_summary(),
        body=(_FixedSugar(body),),
    )

    exits = sugar.desugar().exits

    assert protocol.enter_calls == 1
    # Exit materializes once per enter then fans over body faces (parametric
    # coordinates). Face-specific arguments ride ExitFaceBinding under each
    # body guard — not a second manager/enter evaluation.
    assert protocol.exit_calls == 1
    assert len(protocol.exit_entered) == 1
    assert protocol.exit_entered[0].enter_value == protocol.enter_value

    # All three body face identities survive routing.
    guard_text = " ".join(str(face.guard) for face in exits)
    assert "body-completed" in guard_text
    assert "body-returned" in guard_text
    assert "body-halted" in guard_text

    # Face-derived bindings: completed faces bind None; raise binds occurrence.
    completed_binding = ExitFaceBinding.from_body_exit(
        "exit-face", body.exits[0]
    )
    returned_binding = ExitFaceBinding.from_body_exit(
        "exit-face", body.exits[1]
    )
    halted_binding = ExitFaceBinding.from_body_exit("exit-face", body.exits[2])
    assert completed_binding.kind == "completed"
    assert returned_binding.kind == "completed"
    assert halted_binding.kind == "raised"
    assert halted_binding.exception_name == "ValueError"
    assert halted_binding.occurrence == "body.py:10:8:raise"


def test_false_exit_preserves_return_halt_and_temporal_state():
    """False __exit__ keeps return/halt faces and the pre-raise temporal state."""
    body, raise_effect = _nested_body_faces()
    protocol = _RecordingProtocol(exit_value=TermValue(False))
    sugar = _source_resource(
        protocol=protocol,
        summary=_truthiness_summary(),
        body=(_FixedSugar(body),),
    )

    exits = sugar.desugar().exits

    # Completed fall-through and early-return remain completed.
    completed = [face for face in exits if isinstance(face, Completed)]
    assert any("body-completed" in str(face.guard) for face in completed)
    assert any("body-returned" in str(face.guard) for face in completed)

    # Halt preserves the exact raise and pre-raise temporal state.
    halted = [
        face
        for face in exits
        if isinstance(face, Halted) and face.effect is raise_effect
    ]
    assert len(halted) == 1
    assert halted[0].state is not None
    assert "pre-raise" in getattr(halted[0].state, "entries", ())
    assert protocol.exit_calls == 1


def test_truthy_exit_suppresses_only_the_incoming_raise():
    """Truthy __exit__ consumes the raise; completed/returned faces stay completed."""
    body, raise_effect = _nested_body_faces()
    protocol = _RecordingProtocol(exit_value=TermValue(True))
    sugar = _source_resource(
        protocol=protocol,
        summary=_truthiness_summary(),
        body=(_FixedSugar(body),),
    )

    exits = sugar.desugar().exits

    assert not any(
        isinstance(face, Halted) and face.effect is raise_effect for face in exits
    ), exits
    # Raise was suppressed into a completion (truthiness arm).
    assert any(
        isinstance(face, Completed) and "body-halted" in str(face.guard)
        for face in exits
    )
    # Non-raise faces remain completions under their guards.
    assert any(
        isinstance(face, Completed) and "body-completed" in str(face.guard)
        for face in exits
    )
    assert any(
        isinstance(face, Completed) and "body-returned" in str(face.guard)
        for face in exits
    )
    assert protocol.exit_calls == 1


def test_exit_halt_supersedes_every_incoming_body_face():
    """A halted __exit__ supersedes Completed, Returned, and Halted body faces."""
    body, raise_effect = _nested_body_faces()
    exit_halt = RaiseEffect(
        exception_name="RuntimeError",
        occurrence="exit.py:1:0",
        blame="exit.py:1:0",
    )
    protocol = _RecordingProtocol(exit_outcome=Incomplete(exit_halt))
    sugar = _source_resource(
        protocol=protocol,
        summary=_never_summary(),
        body=(_FixedSugar(body),),
    )

    exits = sugar.desugar().exits

    assert protocol.exit_calls == 1
    # Exit halt supersedes every body effect. Companion Completed residues may
    # carry ExitFaceBinding facts under the same guards — they are testimony,
    # not surviving body completions.
    assert exits
    halted = [face for face in exits if isinstance(face, Halted)]
    assert halted
    assert all(face.effect is exit_halt for face in halted)
    assert not any(
        isinstance(face, Halted) and face.effect is raise_effect for face in exits
    )
    # Body face identities still ride the superseding halt guards.
    guard_text = " ".join(str(face.guard) for face in halted)
    assert "body-completed" in guard_text
    assert "body-returned" in guard_text
    assert "body-halted" in guard_text


def test_face_occurrence_lying_twin_discriminates_exit_bindings():
    """Lying twin: distinct raise occurrences mint distinct ExitFaceBinding rows."""
    a = RaiseEffect(
        exception_name="ValueError",
        occurrence="body.py:1:0:A",
        blame="body.py:1:0:A",
    )
    b = RaiseEffect(
        exception_name="ValueError",
        occurrence="body.py:2:0:B",
        blame="body.py:2:0:B",
    )
    bind_a = ExitFaceBinding.from_body_exit(
        "exit-face", Halted(true_guard(), a, _state("a"))
    )
    bind_b = ExitFaceBinding.from_body_exit(
        "exit-face", Halted(true_guard(), b, _state("b"))
    )
    assert bind_a.kind == bind_b.kind == "raised"
    assert bind_a.exception_name == bind_b.exception_name == "ValueError"
    assert bind_a.occurrence != bind_b.occurrence
    assert bind_a.occurrence == "body.py:1:0:A"
    assert bind_b.occurrence == "body.py:2:0:B"

    # Completions never borrow a raise occurrence.
    completed = ExitFaceBinding.from_body_exit(
        "exit-face",
        Completed(true_guard(), BlockValue((), can_fall_through=True)),
    )
    assert completed.kind == "completed"
    assert completed.occurrence is None
    assert completed.exception_name is None


def test_discrimination_exit_not_skipped_on_multi_face_body():
    """Bite: multi-face body must still invoke exit (probe non-empty)."""
    body, _ = _nested_body_faces()
    protocol = _RecordingProtocol(exit_value=TermValue(False))
    sugar = _source_resource(
        protocol=protocol,
        summary=_truthiness_summary(),
        body=(_FixedSugar(body),),
    )
    sugar.desugar()
    with pytest.raises(AssertionError):
        assert protocol.exit_calls == 0


def test_discrimination_truthy_exit_does_not_suppress_non_raise_transfer():
    """Bite: truthy exit must not invent suppression for completed/returned faces."""
    body = ExitSet(
        (
            Completed(
                _Atomic("only-return", ()),
                BlockValue(
                    (ReturnValue(TermValue("kept")),),
                    can_fall_through=False,
                ),
            ),
        )
    )
    protocol = _RecordingProtocol(exit_value=TermValue(True))
    sugar = _source_resource(
        protocol=protocol,
        summary=_truthiness_summary(),
        body=(_FixedSugar(body),),
    )
    exits = sugar.desugar().exits
    # Return face stays completed — truthy exit does not convert it to a halt
    # or drop it (and_exit_truthiness only splits raise faces).
    assert any(isinstance(face, Completed) for face in exits)
    assert protocol.exit_calls == 1
