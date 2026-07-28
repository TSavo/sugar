"""Stack a factored assertion manager with a source-resource manager.

Source order is nesting order: first manager is outer (enter first, exit last).
Each outgoing body face runs both required exits exactly once. Assertion
suppression (consume matching raise / unmet / residual) stays separate from
resource disposition (NeverSuppresses / truthiness).
"""

from __future__ import annotations

from types import SimpleNamespace

from sugar_lift_py_tests.context_manager_contract import (
    CallParameterV1,
    EffectBoundarySemanticsV1,
    ExceptionInfoBindingV1,
    ExpectsModeV1,
    FormalArgumentProjectionV1,
    ImportSignatureV2,
    LiteralDefaultV1,
    NeverSuppressesDispositionV1,
    NoDefaultV1,
    NoMessagePatternV1,
    OptionalFormalArgumentProjectionV1,
    PositionalOrKeywordV1,
    RaiseEffectKindV1,
    ReturnTruthinessDispositionV1,
)
from sugar_lift_py_tests.context_manager_resolution import SourceFragmentCoordinateV1
from sugar_lift_py_tests.effect.expectation_not_met_effect import (
    ExpectationNotMetEffect,
)
from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
from sugar_lift_py_tests.floor import StringValue, TermValue
from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
from sugar_lift_py_tests.ir import PrimitiveSort, _Atomic, ctor
from sugar_lift_py_tests.outcome import Complete, Completed, Halted, Incomplete
from sugar_lift_py_tests.outcome.exit_set import ExitSet
from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock
from sugar_lift_py_tests.sugar.method_call_sugar import MethodCallSugar
from sugar_lift_py_tests.sugar.resource_coord_sugar import (
    ExitTracebackRefSugar,
    ExitTypeRefSugar,
    ExitValueRefSugar,
    ManagerRefSugar,
)
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.with_effect_boundary_sugar import (
    WithEffectBoundarySugar,
)
from sugar_lift_py_tests.sugar.with_source_resource_sugar import (
    WithSourceResourceSugar,
)


def _identity(name: str):
    from sugar_lift_py_tests.ir import str_const

    return ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const(name)],
    )


class _Expected:
    def __init__(self, name: str):
        self.identity = _identity(name)

    def exception_type_identity(self):
        return self.identity


def _state(marker: str):
    return _ReducedBlock(
        entries=(marker,), can_fall_through=False, fall_through=()
    )


class Fixed(Sugar):
    def __init__(self, outcome):
        self.outcome = outcome

    def desugar(self, ctx=None):
        del ctx
        return self.outcome

    @classmethod
    def witnesses(cls):
        return ()


class _RecordingProtocol:
    """Records enter/exit order and count."""

    def __init__(self, *, name: str, exit_value=None, exit_outcome=None):
        self.name = name
        self.enter_calls = 0
        self.exit_calls = 0
        self.order = []
        self.exit_value = exit_value if exit_value is not None else TermValue(False)
        self._exit_outcome = exit_outcome
        self.enter_value = TermValue(f"enter-{name}")

    def enter_resource_outcome(self, ctx=None):
        del ctx
        self.enter_calls += 1
        self.order.append(f"enter:{self.name}")
        return Complete(SimpleNamespace(enter_value=self.enter_value))

    def exit_outcome_for(self, entered, ctx=None):
        del ctx
        self.exit_calls += 1
        self.order.append(f"exit:{self.name}")
        if self._exit_outcome is not None:
            return self._exit_outcome
        return Complete(self.exit_value)


def _protocol_calls(slot: str, face_id: str):
    enter_definition = SourceFragmentCoordinateV1(
        "blake3-512:" + "e" * 128, 1, 0, 1, 1
    )
    exit_definition = SourceFragmentCoordinateV1(
        "blake3-512:" + "x" * 128, 2, 0, 2, 1
    )
    enter = MethodCallSugar(
        receiver=ManagerRefSugar(slot_id=slot, site=None),
        name="__enter__",
        args=(),
        native_definition_coordinate=enter_definition,
        site=None,
    )
    exit_ = MethodCallSugar(
        receiver=ManagerRefSugar(slot_id=slot, site=None),
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


def _source_resource(*, protocol, summary, body, slot="resource-slot", face_id="res-exit"):
    enter, exit_, enter_def, exit_def = _protocol_calls(slot, face_id)
    return WithSourceResourceSugar(
        manager=Fixed(Complete(TermValue(1))),
        enter=enter,
        exit=exit_,
        enter_definition=enter_def,
        exit_definition=exit_def,
        protocol=protocol,
        summary=summary,
        body=body,
        manager_slot_id=slot,
        enter_slot_id=None,
        exit_face_id=face_id,
        site="stack-resource.py:1:0",
    )


def _never_summary():
    return SimpleNamespace(
        semantics=SimpleNamespace(
            exit=SimpleNamespace(disposition=NeverSuppressesDispositionV1())
        )
    )


def _truthiness_summary():
    return SimpleNamespace(
        semantics=SimpleNamespace(
            exit=SimpleNamespace(disposition=ReturnTruthinessDispositionV1())
        )
    )


def _factored_boundary_faces():
    none_face = EffectBoundarySemanticsV1(
        ExpectsModeV1(),
        RaiseEffectKindV1(),
        FormalArgumentProjectionV1(0),
        NoMessagePatternV1(),
        ExceptionInfoBindingV1(),
    )
    pattern_face = EffectBoundarySemanticsV1(
        ExpectsModeV1(),
        RaiseEffectKindV1(),
        FormalArgumentProjectionV1(0),
        OptionalFormalArgumentProjectionV1(1),
        ExceptionInfoBindingV1(),
    )
    return ExitSet(
        (
            Completed(_Atomic("match-none-face", ()), none_face),
            Completed(_Atomic("match-pattern-face", ()), pattern_face),
        )
    )


def _factored_boundary(body: ExitSet, *, pattern=None, observation_slot_id="excinfo"):
    expected = _Expected("ValueError")
    if pattern is None:
        pattern = StringValue("needle")
    parameters = (
        CallParameterV1(
            "expected",
            PrimitiveSort("Value"),
            PositionalOrKeywordV1(),
            True,
            NoDefaultV1(),
        ),
        CallParameterV1(
            "match",
            PrimitiveSort("Value"),
            PositionalOrKeywordV1(),
            False,
            LiteralDefaultV1({"kind": "ctor", "name": "None", "args": []}),
        ),
    )
    manager_value = CallSiteValue(
        target_name="expect",
        arg_values=(expected, pattern),
        parameters=tuple(p.name for p in parameters),
        term=ctor("call:expect", []),
        body=None,
        keyword_names=(),
    )
    return WithEffectBoundarySugar(
        manager=Fixed(Complete(manager_value)),
        body=(Fixed(body),),
        semantics=None,
        contract_ref=SimpleNamespace(
            import_signature=ImportSignatureV2(parameters)
        ),
        context_manager_edge=None,
        boundary_faces=_factored_boundary_faces(),
        observation_slot_id=observation_slot_id,
        site="stack-boundary.py:1:0",
    )


def _raise(name: str, marker: str, *, message=None, occurrence=None):
    occ = occurrence or f"body.py:1:0:{marker}"
    raised_value = None
    if message is not None:
        raised_value = CallSiteValue(
            name,
            (message,),
            ("message",),
            ctor(f"call:{name}", []),
            None,
        )
    return Halted(
        _Atomic(f"body-{marker}", ()),
        RaiseEffect(
            exception_name=name,
            blame=occ,
            occurrence=occ,
            exception_type_coordinate=_identity(name),
            exception_type_mro=(_identity(name),),
            raised_value=raised_value,
            producer_node_owner="StackBody.desugar",
        ),
        _state(marker),
    )


def _observed_binding(face):
    from sugar_lift_py_tests.effect_router import ObservedEffectBinding

    record = face.value if isinstance(face, Completed) else face.state
    entries = getattr(record, "entries", ()) or ()
    return next(
        (entry for entry in entries if isinstance(entry, ObservedEffectBinding)),
        None,
    )


def _as_exitset(outcome):
    from sugar_lift_py_tests.outcome import outcome_to_exitset

    if isinstance(outcome, ExitSet):
        return outcome
    return outcome_to_exitset(outcome)


def _multi_body():
    matching = _raise(
        "ValueError",
        "matching",
        occurrence="body.py:10:8:matching",
        message=StringValue("needle"),
    )
    mismatch = _raise(
        "TypeError",
        "mismatch",
        occurrence="body.py:12:8:mismatch",
        message=StringValue("other"),
    )
    completed = Completed(_Atomic("body-completed", ()), _state("completed-no-raise"))
    return ExitSet((matching, mismatch, completed)), matching.effect, mismatch.effect


# ---------------------------------------------------------------------------
# Source order + dual exit
# ---------------------------------------------------------------------------


def test_resource_outer_assertion_inner_enter_exit_source_order():
    """with resource, expect: enter resource → body/assert → exit resource.

    Assertion has no enter/exit protocol; resource enter once, exit once per
    construction (fanned across body faces). Source order: resource outer.
    """
    body, matching_effect, mismatch_effect = _multi_body()
    protocol = _RecordingProtocol(name="resource")
    boundary = _factored_boundary(body)
    outer = _source_resource(
        protocol=protocol,
        summary=_never_summary(),
        body=(boundary,),
    )
    exits = _as_exitset(outer.desugar())
    assert protocol.enter_calls == 1
    # Parametric exit: once per enter, not once per body face construction.
    assert protocol.exit_calls == 1
    assert protocol.order == ["enter:resource", "exit:resource"]

    # Both message faces survive the outer resource fan-out.
    text = " ".join(str(face.guard) for face in exits.exits)
    assert "match-none-face" in text
    assert "match-pattern-face" in text
    assert "body-matching" in text
    assert "body-mismatch" in text

    # Assertion authority: matching consumed with binding; mismatch restored.
    assert any(
        isinstance(face, Completed) and _observed_binding(face) is not None
        and _observed_binding(face).effect is matching_effect
        for face in exits.exits
    )
    assert any(
        isinstance(face, Halted) and face.effect is mismatch_effect
        for face in exits.exits
    )
    # Unmet still ExpectationNotMet (assertion authority, not resource).
    assert any(
        isinstance(face, Halted) and isinstance(face.effect, ExpectationNotMetEffect)
        for face in exits.exits
    )


def test_assertion_outer_resource_inner_enter_exit_source_order():
    """with expect, resource: enter resource (inner) once; exit once; assert outer.

    Outer assertion routes the whole resource ExitSet under dual message faces.
    """
    body, matching_effect, mismatch_effect = _multi_body()
    protocol = _RecordingProtocol(name="resource")
    resource = _source_resource(
        protocol=protocol,
        summary=_never_summary(),
        body=(Fixed(body),),
    )
    # Outer factored boundary over the resource sugar as its body suite.
    # Manager for assertion still factored faces.
    expected = _Expected("ValueError")
    pattern = StringValue("needle")
    parameters = (
        CallParameterV1(
            "expected",
            PrimitiveSort("Value"),
            PositionalOrKeywordV1(),
            True,
            NoDefaultV1(),
        ),
        CallParameterV1(
            "match",
            PrimitiveSort("Value"),
            PositionalOrKeywordV1(),
            False,
            LiteralDefaultV1({"kind": "ctor", "name": "None", "args": []}),
        ),
    )
    manager_value = CallSiteValue(
        target_name="expect",
        arg_values=(expected, pattern),
        parameters=tuple(p.name for p in parameters),
        term=ctor("call:expect", []),
        body=None,
        keyword_names=(),
    )
    outer = WithEffectBoundarySugar(
        manager=Fixed(Complete(manager_value)),
        body=(resource,),
        semantics=None,
        contract_ref=SimpleNamespace(
            import_signature=ImportSignatureV2(parameters)
        ),
        context_manager_edge=None,
        boundary_faces=_factored_boundary_faces(),
        observation_slot_id="excinfo",
        site="stack-boundary-outer.py:1:0",
    )
    exits = _as_exitset(outer.desugar())
    assert protocol.enter_calls == 1
    assert protocol.exit_calls == 1
    assert protocol.order == ["enter:resource", "exit:resource"]

    text = " ".join(str(face.guard) for face in exits.exits)
    assert "match-none-face" in text
    assert "match-pattern-face" in text

    assert any(
        isinstance(face, Completed)
        and _observed_binding(face) is not None
        and _observed_binding(face).effect is matching_effect
        for face in exits.exits
    )
    assert any(
        isinstance(face, Halted) and face.effect is mismatch_effect
        for face in exits.exits
    )


def test_each_outgoing_face_keeps_both_manager_identities():
    """Factored message guards + resource face binding facts ride every path."""
    body, matching_effect, _ = _multi_body()
    protocol = _RecordingProtocol(name="resource")
    boundary = _factored_boundary(body)
    outer = _source_resource(
        protocol=protocol,
        summary=_never_summary(),
        body=(boundary,),
        face_id="res-exit",
    )
    exits = _as_exitset(outer.desugar())
    assert protocol.exit_calls == 1
    # Every face still carries a factored message-face guard.
    for face in exits.exits:
        text = str(face.guard)
        assert (
            "match-none-face" in text or "match-pattern-face" in text
        ), text


def test_suppression_authorities_remain_separate():
    """Assertion consumes matching raise; resource NeverSuppresses does not steal.

    Twin: truthy resource exit would suppress raises, but assertion still owns
    the matching face when it is inner (resource sees assertion's result).
    """
    body, matching_effect, mismatch_effect = _multi_body()

    # Resource outer + NeverSuppresses: residual mismatch restored as-is.
    p_never = _RecordingProtocol(name="never")
    never_stack = _source_resource(
        protocol=p_never,
        summary=_never_summary(),
        body=(_factored_boundary(body),),
    )
    never_exits = _as_exitset(never_stack.desugar())
    assert any(
        isinstance(face, Halted) and face.effect is mismatch_effect
        for face in never_exits.exits
    )
    # Matching was already consumed by assertion → Completed, not re-halted.
    assert any(
        isinstance(face, Completed)
        and _observed_binding(face) is not None
        and _observed_binding(face).effect is matching_effect
        for face in never_exits.exits
    )

    # Resource outer + truthy exit: only residual raises could be suppressed;
    # assertion-consumed completions stay completed (no re-raise invention).
    p_truthy = _RecordingProtocol(name="truthy", exit_value=TermValue(True))
    truthy_stack = _source_resource(
        protocol=p_truthy,
        summary=_truthiness_summary(),
        body=(_factored_boundary(body),),
    )
    truthy_exits = _as_exitset(truthy_stack.desugar())
    # Mismatch raise is suppressed by truthy resource exit.
    assert not any(
        isinstance(face, Halted) and face.effect is mismatch_effect
        for face in truthy_exits.exits
    ), truthy_exits.exits
    # Assertion's consumed matching face still completes with binding.
    assert any(
        isinstance(face, Completed)
        and _observed_binding(face) is not None
        and _observed_binding(face).effect is matching_effect
        for face in truthy_exits.exits
    )
    # Unmet ExpectationNotMet is not a RaiseEffect — truthiness does not
    # invent suppression for it; NeverSuppresses path keeps it halted.
    assert any(
        isinstance(face, Halted) and isinstance(face.effect, ExpectationNotMetEffect)
        for face in never_exits.exits
    )


def test_twin_source_order_swaps_outer_type():
    """Discrimination: resource-first vs assertion-first swap the outer sugar."""
    body, _, _ = _multi_body()
    protocol_a = _RecordingProtocol(name="a")
    protocol_b = _RecordingProtocol(name="b")

    resource_outer = _source_resource(
        protocol=protocol_a,
        summary=_never_summary(),
        body=(_factored_boundary(body),),
    )
    assert isinstance(resource_outer, WithSourceResourceSugar)
    assert isinstance(resource_outer.body[0], WithEffectBoundarySugar)

    # Assertion outer wrapping resource.
    resource_inner = _source_resource(
        protocol=protocol_b,
        summary=_never_summary(),
        body=(Fixed(body),),
    )
    expected = _Expected("ValueError")
    parameters = (
        CallParameterV1(
            "expected",
            PrimitiveSort("Value"),
            PositionalOrKeywordV1(),
            True,
            NoDefaultV1(),
        ),
        CallParameterV1(
            "match",
            PrimitiveSort("Value"),
            PositionalOrKeywordV1(),
            False,
            LiteralDefaultV1({"kind": "ctor", "name": "None", "args": []}),
        ),
    )
    manager_value = CallSiteValue(
        target_name="expect",
        arg_values=(expected, StringValue("needle")),
        parameters=tuple(p.name for p in parameters),
        term=ctor("call:expect", []),
        body=None,
        keyword_names=(),
    )
    assertion_outer = WithEffectBoundarySugar(
        manager=Fixed(Complete(manager_value)),
        body=(resource_inner,),
        semantics=None,
        contract_ref=SimpleNamespace(
            import_signature=ImportSignatureV2(parameters)
        ),
        context_manager_edge=None,
        boundary_faces=_factored_boundary_faces(),
        observation_slot_id="excinfo",
        site="order-twin.py:1:0",
    )
    assert isinstance(assertion_outer, WithEffectBoundarySugar)
    assert isinstance(assertion_outer.body[0], WithSourceResourceSugar)
    assert type(resource_outer) is not type(assertion_outer)

    # Both evaluate their resource enter/exit once.
    _as_exitset(resource_outer.desugar())
    _as_exitset(assertion_outer.desugar())
    assert protocol_a.enter_calls == protocol_a.exit_calls == 1
    assert protocol_b.enter_calls == protocol_b.exit_calls == 1


def test_excinfo_only_on_consumed_occurrence_through_stack():
    """Stacked resource does not invent or rebind excinfo on residual faces."""
    body, matching_effect, mismatch_effect = _multi_body()
    protocol = _RecordingProtocol(name="resource")
    outer = _source_resource(
        protocol=protocol,
        summary=_never_summary(),
        body=(_factored_boundary(body),),
    )
    exits = _as_exitset(outer.desugar())
    bound = {
        _observed_binding(face).effect
        for face in exits.exits
        if _observed_binding(face) is not None
    }
    assert matching_effect in bound
    assert mismatch_effect not in bound
    assert all(
        e.occurrence == "body.py:10:8:matching" for e in bound
    )
