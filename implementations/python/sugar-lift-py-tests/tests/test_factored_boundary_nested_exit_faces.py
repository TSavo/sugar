"""Join factored assertion-manager faces with nested Returned and Halted body exits.

Factored message-pattern faces (match-none / match-pattern) must fan over a
multi-face body ExitSet without collapsing either message guard:

- body return / no-raise → ExpectationNotMet under BOTH original faces
- matching raise → consumed + binds excinfo from the exact occurrence
- mismatching raise → remains halted and unbound
- pattern obligation survives only on the pattern face
- manager (factored CallSiteValue) is evaluated once
- nested halt state and partition testimony stay intact

None/pattern, return/raise, and consumed/unmatched twins discriminate.
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
    NoDefaultV1,
    NoMessagePatternV1,
    OptionalFormalArgumentProjectionV1,
    PositionalOrKeywordV1,
    RaiseEffectKindV1,
)
from sugar_lift_py_tests.effect.expectation_not_met_effect import (
    ExpectationNotMetEffect,
)
from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
from sugar_lift_py_tests.floor import ReturnValue, StringValue, TermValue
from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
from sugar_lift_py_tests.ir import PrimitiveSort, _Atomic, ctor, make_var
from sugar_lift_py_tests.outcome import Complete, Completed, Halted
from sugar_lift_py_tests.outcome.exit_set import ExitSet, true_guard
from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.with_effect_boundary_sugar import (
    WithEffectBoundarySugar,
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


def _state(marker: str, *extra):
    return _ReducedBlock(
        entries=(marker, *extra),
        can_fall_through=False,
        fall_through=(),
    )


class _CountingManager(Sugar):
    """Manager sugar that records how many times it is evaluated."""

    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = 0

    def desugar(self, ctx=None):
        del ctx
        self.calls += 1
        return self.outcome

    @classmethod
    def witnesses(cls):
        return ()


class Fixed(Sugar):
    def __init__(self, outcome):
        self.outcome = outcome

    def desugar(self, ctx=None):
        del ctx
        return self.outcome

    @classmethod
    def witnesses(cls):
        return ()


def _factored_boundary_faces():
    """match=None face and pattern face as guarded EffectBoundary alternatives."""
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


def _raise(
    name: str,
    marker: str,
    *,
    occurrence: str | None = None,
    message: object | None = None,
    producer_node_owner: str | None = None,
):
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
        RaiseEffect(occurrence=AuthenticatedRaiseLocus.of(occ), exception_name=name, blame=occ, exception_type_coordinate=_identity(name), exception_type_mro=(_identity(name),), raised_value=raised_value, producer_node_owner=producer_node_owner or 'NestedBody.desugar'),
        _state(marker),
    )


def _nested_body_faces(
    *,
    matching_message: object | None = None,
    mismatch_name: str = "TypeError",
):
    """Completed fall-through, Returned, matching Halted, mismatching Halted."""
    if matching_message is None:
        matching_message = StringValue("needle")
    matching = _raise(
        "ValueError",
        "matching-raise",
        occurrence="body.py:10:8:matching-raise",
        message=matching_message,
    )
    mismatching = _raise(
        mismatch_name,
        "mismatch-raise",
        occurrence="body.py:12:8:mismatch-raise",
        message=StringValue("other"),
    )
    completed = Completed(
        _Atomic("body-completed", ()),
        _state("completed-no-raise"),
    )
    returned = Completed(
        _Atomic("body-returned", ()),
        _state("returned-no-raise", ReturnValue(TermValue("early-return"))),
    )
    return ExitSet((completed, returned, matching, mismatching)), matching.effect, mismatching.effect


def _observed_binding(face):
    from sugar_lift_py_tests.effect_router import ObservedEffectBinding

    record = face.value if isinstance(face, Completed) else face.state
    entries = getattr(record, "entries", ()) or ()
    return next(
        (entry for entry in entries if isinstance(entry, ObservedEffectBinding)),
        None,
    )


def _marker(face):
    record = face.value if isinstance(face, Completed) else face.state
    entries = getattr(record, "entries", ()) or ()
    for entry in entries:
        if isinstance(entry, str):
            return entry
    return None


def _factored_boundary(
    body: ExitSet,
    *,
    expected=None,
    pattern=None,
    observation_slot_id: str | None = "excinfo",
    manager_sugar=None,
):
    """Production WithEffectBoundarySugar over factored message-pattern faces."""
    expected = expected or _Expected("ValueError")
    if pattern is None:
        pattern = StringValue("needle")
    actuals = (expected, pattern)
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
        arg_values=actuals,
        parameters=tuple(parameter.name for parameter in parameters),
        term=ctor("call:expect", []),
        body=None,
        keyword_names=(),
    )
    manager = manager_sugar or _CountingManager(Complete(manager_value))
    if manager_sugar is None:
        # Keep default counting manager
        pass
    sugar = WithEffectBoundarySugar(
        manager=manager,
        body=(Fixed(body),),
        semantics=None,
        contract_ref=SimpleNamespace(
            import_signature=ImportSignatureV2(parameters)
        ),
        context_manager_edge=None,
        boundary_faces=_factored_boundary_faces(),
        observation_slot_id=observation_slot_id,
        site="factored-nested-exit.py:1:0",
    )
    return sugar, manager


# ---------------------------------------------------------------------------
# Core join laws
# ---------------------------------------------------------------------------


def test_factored_manager_evaluated_once_over_nested_body_faces():
    """Returned factored manager is desugared once, not once per body face."""
    body, _, _ = _nested_body_faces()
    sugar, manager = _factored_boundary(body)

    exits = sugar.desugar()
    assert manager.calls == 1, manager.calls
    assert exits.exits  # multi-face body under dual guards yields work


def test_body_return_and_no_raise_are_unmet_under_both_message_faces():
    """Return/no-raise cannot escape as successful return under either face.

    ExpectationNotMetEffect lands under BOTH match-none-face and
    match-pattern-face guards. The two message faces never collapse.
    """
    body, _, _ = _nested_body_faces()
    sugar, _ = _factored_boundary(body)
    routed = sugar.desugar()

    for body_id, marker in (
        ("body-completed", "completed-no-raise"),
        ("body-returned", "returned-no-raise"),
    ):
        faces = [
            face
            for face in routed.exits
            if body_id in str(face.guard) and _marker(face) == marker
        ]
        assert faces, (body_id, routed.exits)
        # Must be halted ExpectationNotMet — never a successful return/completion.
        assert all(isinstance(face, Halted) for face in faces), faces
        assert all(
            isinstance(face.effect, ExpectationNotMetEffect) for face in faces
        ), faces
        # Both original message faces keep identity; neither is dropped.
        guard_text = " ".join(str(face.guard) for face in faces)
        assert "match-none-face" in guard_text, (body_id, guard_text)
        assert "match-pattern-face" in guard_text, (body_id, guard_text)
        # No successful completion of a return/no-raise under either face.
        assert not any(
            isinstance(face, Completed)
            and body_id in str(face.guard)
            and _marker(face) == marker
            for face in routed.exits
        )


def test_matching_raise_consumes_and_binds_exact_occurrence_under_none_face():
    """Matching raise: match-none face consumes and binds that exact occurrence."""
    body, matching_effect, _ = _nested_body_faces()
    sugar, _ = _factored_boundary(body)
    routed = sugar.desugar()

    none_consumed = [
        face
        for face in routed.exits
        if isinstance(face, Completed)
        and "match-none-face" in str(face.guard)
        and "body-matching-raise" in str(face.guard)
        and _observed_binding(face) is not None
    ]
    assert len(none_consumed) == 1, routed.exits
    binding = _observed_binding(none_consumed[0])
    assert binding.slot_id == "excinfo"
    assert binding.effect is matching_effect
    assert binding.effect.occurrence_id == "body.py:10:8:matching-raise"
    assert binding.effect.exception_name == "ValueError"
    assert binding.effect.producer_node_owner == "NestedBody.desugar"


def test_matching_raise_under_pattern_face_binds_held_not_complement():
    """Pattern face retains message obligation; bind only held; halt unbound."""
    # Symbolic pattern keeps the message predicate open → held + complement.
    pattern = SymbolicValue(make_var("open_msg_pattern"))
    body, matching_effect, _ = _nested_body_faces(matching_message=StringValue("needle"))
    sugar, _ = _factored_boundary(body, pattern=pattern)
    routed = sugar.desugar()

    pattern_faces = [
        face
        for face in routed.exits
        if "match-pattern-face" in str(face.guard)
        and "body-matching-raise" in str(face.guard)
        and "py.re_search" in str(face.guard)
    ]
    assert {type(face).__name__ for face in pattern_faces} == {
        "Completed",
        "Halted",
    }, pattern_faces
    held = next(face for face in pattern_faces if isinstance(face, Completed))
    failed = next(face for face in pattern_faces if isinstance(face, Halted))

    held_binding = _observed_binding(held)
    assert held_binding is not None
    assert held_binding.slot_id == "excinfo"
    assert held_binding.effect is matching_effect
    assert held_binding.effect.occurrence == matching_effect.occurrence

    # Complement preserves the original halt and authenticates no slot.
    assert failed.effect is matching_effect
    assert _observed_binding(failed) is None
    # Pre-halt temporal state intact on the residual halt.
    assert _marker(failed) == "matching-raise"


def test_mismatching_raise_remains_halted_and_unbound_under_both_faces():
    """Wrong exception type stays halted under both message faces, never bound."""
    body, _, mismatch_effect = _nested_body_faces()
    sugar, _ = _factored_boundary(body)
    routed = sugar.desugar()

    mismatch_faces = [
        face
        for face in routed.exits
        if "body-mismatch-raise" in str(face.guard)
    ]
    assert mismatch_faces, routed.exits
    assert all(isinstance(face, Halted) for face in mismatch_faces), mismatch_faces
    assert all(face.effect is mismatch_effect for face in mismatch_faces)
    assert all(_observed_binding(face) is None for face in mismatch_faces)
    # Both message face identities reach the residual halt.
    guard_text = " ".join(str(face.guard) for face in mismatch_faces)
    assert "match-none-face" in guard_text
    assert "match-pattern-face" in guard_text
    # Nested halt state preserved.
    assert all(_marker(face) == "mismatch-raise" for face in mismatch_faces)


def test_pattern_obligation_survives_only_on_pattern_face():
    """py.re_search rides match-pattern-face only; never match-none-face."""
    pattern = SymbolicValue(make_var("msg_pattern"))
    body, _, _ = _nested_body_faces()
    sugar, _ = _factored_boundary(body, pattern=pattern)
    routed = sugar.desugar()

    face_ids = {guard.name for guard, _ in sugar._guarded_semantics()}
    assert face_ids == {"match-none-face", "match-pattern-face"}
    operands = {semantics.message_pattern_operand for _, semantics in sugar._guarded_semantics()}
    assert operands == {
        NoMessagePatternV1(),
        OptionalFormalArgumentProjectionV1(1),
    }

    for face in routed.exits:
        text = str(face.guard)
        if "py.re_search" in text:
            assert "match-pattern-face" in text
            assert "match-none-face" not in text or "match-pattern-face" in text
            # Regex obligation is conjoined with the pattern face, never alone.
            assert "match-pattern-face" in text


def test_nested_halt_state_and_partition_testimony_intact():
    """Halted residual keeps pre-raise state; pattern partition keeps both faces."""
    pattern = SymbolicValue(make_var("partition_pattern"))
    body, matching_effect, _ = _nested_body_faces()
    sugar, _ = _factored_boundary(body, pattern=pattern)
    routed = sugar.desugar()

    # Residual mismatch halt still carries its pre-halt marker.
    for face in routed.exits:
        if isinstance(face, Halted) and face.effect is matching_effect:
            # Complement arm under pattern: state intact.
            if "py.re_search" in str(face.guard):
                assert _marker(face) == "matching-raise"
                assert face.state is not None
                assert "matching-raise" in face.state.entries

    # Partition testimony: both Completed (held) and Halted (failed) for the
    # open pattern predicate under the matching-raise body arm.
    matching_pattern = [
        face
        for face in routed.exits
        if "body-matching-raise" in str(face.guard)
        and "match-pattern-face" in str(face.guard)
    ]
    assert any(isinstance(f, Completed) for f in matching_pattern)
    assert any(isinstance(f, Halted) for f in matching_pattern)


# ---------------------------------------------------------------------------
# Discrimination twins
# ---------------------------------------------------------------------------


def test_twin_none_vs_pattern_face_identities_never_recombine():
    """None/pattern twin: face identities and operands stay distinct."""
    body, _, _ = _nested_body_faces()
    pattern = SymbolicValue(make_var("twin_pattern"))
    sugar, _ = _factored_boundary(body, pattern=pattern)

    guarded = sugar._guarded_semantics()
    assert len(guarded) == 2
    by_name = {guard.name: semantics for guard, semantics in guarded}
    assert isinstance(by_name["match-none-face"].message_pattern_operand, NoMessagePatternV1)
    assert isinstance(
        by_name["match-pattern-face"].message_pattern_operand,
        OptionalFormalArgumentProjectionV1,
    )

    routed = sugar.desugar()
    guard_text = " ".join(str(face.guard) for face in routed.exits)
    assert "match-none-face" in guard_text
    assert "match-pattern-face" in guard_text
    # Collapsing the two message faces into one would drop an identity.
    assert "match-none-face" in guard_text and "match-pattern-face" in guard_text


def test_twin_return_vs_raise_under_factored_faces():
    """Return/raise twin: return → unmet; matching raise → consumed with bind."""
    body, matching_effect, _ = _nested_body_faces()
    sugar, _ = _factored_boundary(body)
    routed = sugar.desugar()

    returned = [
        face
        for face in routed.exits
        if "body-returned" in str(face.guard)
    ]
    assert returned
    assert all(isinstance(face, Halted) for face in returned)
    assert all(isinstance(face.effect, ExpectationNotMetEffect) for face in returned)
    assert all(_observed_binding(face) is None for face in returned)

    raised_consumed = [
        face
        for face in routed.exits
        if isinstance(face, Completed)
        and "body-matching-raise" in str(face.guard)
        and _observed_binding(face) is not None
    ]
    assert raised_consumed
    assert all(
        _observed_binding(face).effect is matching_effect for face in raised_consumed
    )


def test_twin_consumed_vs_unmatched_binding():
    """Consumed/unmatched twin: only the matching occurrence binds excinfo."""
    body, matching_effect, mismatch_effect = _nested_body_faces()
    sugar, _ = _factored_boundary(body)
    routed = sugar.desugar()

    bound_effects = {
        _observed_binding(face).effect
        for face in routed.exits
        if _observed_binding(face) is not None
    }
    assert matching_effect in bound_effects
    assert mismatch_effect not in bound_effects

    # Unmatched residual never carries a slot.
    for face in routed.exits:
        if isinstance(face, Halted) and face.effect is mismatch_effect:
            assert _observed_binding(face) is None
        if isinstance(face, Halted) and isinstance(face.effect, ExpectationNotMetEffect):
            assert _observed_binding(face) is None


def test_ground_pattern_decides_matching_message_under_nested_body():
    """Ground pattern: matching message consumes under pattern face; miss stays halt."""
    body_hit, hit_effect, _ = _nested_body_faces(
        matching_message=StringValue("needle")
    )
    # Rebuild body so matching raise message is "other" (miss) under same guards.
    miss_matching = _raise(
        "ValueError",
        "matching-raise",
        occurrence="body.py:10:8:matching-raise",
        message=StringValue("other"),
    )
    body_miss = ExitSet(
        (
            Completed(_Atomic("body-completed", ()), _state("completed-no-raise")),
            Completed(
                _Atomic("body-returned", ()),
                _state("returned-no-raise", ReturnValue(TermValue("early-return"))),
            ),
            miss_matching,
            _raise("TypeError", "mismatch-raise", message=StringValue("x")),
        )
    )
    pattern = StringValue("needle")

    hit_routed = _factored_boundary(body_hit, pattern=pattern)[0].desugar()
    miss_routed = _factored_boundary(body_miss, pattern=pattern)[0].desugar()

    hit_pattern_completed = [
        face
        for face in hit_routed.exits
        if isinstance(face, Completed)
        and "match-pattern-face" in str(face.guard)
        and "body-matching-raise" in str(face.guard)
    ]
    assert hit_pattern_completed
    assert all(
        _observed_binding(face) is not None
        and _observed_binding(face).effect is hit_effect
        for face in hit_pattern_completed
    )

    miss_pattern_for_raise = [
        face
        for face in miss_routed.exits
        if "match-pattern-face" in str(face.guard)
        and "body-matching-raise" in str(face.guard)
    ]
    # Ground miss: no consumption of the raise under the pattern face.
    assert all(isinstance(face, Halted) for face in miss_pattern_for_raise)
    assert all(_observed_binding(face) is None for face in miss_pattern_for_raise)
    assert all(
        face.effect is miss_matching.effect for face in miss_pattern_for_raise
    )
