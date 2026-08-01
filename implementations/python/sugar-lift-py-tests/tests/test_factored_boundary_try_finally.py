"""Join factored assertion boundaries with try/finally.

Factored message-pattern faces (match-none / match-pattern) route a body, then
try/finally (``ExitSet.and_finally`` — the same algebra ``TrySugar`` fans) runs
cleanup over every outgoing face without collapsing either message guard:

- matching and mismatching faces retain original guards through try
- finally runs on consumed, unmet, and retained-halt paths
- ordinary cleanup restores incoming result/state
- terminal cleanup overrides
- excinfo binds only the consumed occurrence
- None/pattern and restoring/overriding twins discriminate
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
from sugar_lift_py_tests.floor import StringValue
from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
from sugar_lift_py_tests.ir import PrimitiveSort, _Atomic, ctor, make_var
from sugar_lift_py_tests.outcome import Complete, Completed, Halted
from sugar_lift_py_tests.outcome.exit_set import ExitSet
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
        RaiseEffect(exception_type_coordinate=_identity(name), occurrence=AuthenticatedRaiseLocus.of(occ), exception_name=name, blame=occ, exception_type_mro=(_identity(name),), raised_value=raised_value, producer_node_owner='TryFinallyBody.desugar'),
        _state(marker),
    )


def _multi_path_body():
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
    completed = Completed(
        _Atomic("body-completed", ()),
        _state("completed-no-raise"),
    )
    return (
        ExitSet((matching, mismatch, completed)),
        matching.effect,
        mismatch.effect,
    )


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
        site="factored-try-finally.py:1:0",
    )


def _boundary_exitset(body: ExitSet, **kwargs) -> ExitSet:
    outcome = _factored_boundary(body, **kwargs).desugar()
    assert isinstance(outcome, ExitSet), type(outcome)
    return outcome


def _join_try_finally(incoming: ExitSet, cleanup_es: ExitSet, *, restores: bool = True):
    """try/finally algebra: cleanup fans over every face (``TrySugar`` shell)."""
    calls = {"n": 0}

    def cleanup():
        calls["n"] += 1
        return cleanup_es

    if restores:
        after = incoming.and_finally(cleanup)
    else:
        after = incoming.and_finally(cleanup, cleanup_restores=lambda _v: False)
    return after, calls


# ---------------------------------------------------------------------------
# Core laws
# ---------------------------------------------------------------------------


def test_message_faces_retain_original_guards_through_try():
    """Matching and mismatching faces keep match-none / match-pattern guards."""
    body, _, _ = _multi_path_body()
    pattern = SymbolicValue(make_var("open_pattern"))
    incoming = _boundary_exitset(body, pattern=pattern)
    cleanup = ExitSet.completed("cleanup-done")
    routed, calls = _join_try_finally(incoming, cleanup)
    assert calls["n"] == 1

    guard_text = " ".join(str(face.guard) for face in routed.exits)
    assert "match-none-face" in guard_text
    assert "match-pattern-face" in guard_text
    assert "body-matching" in guard_text
    assert "body-mismatch" in guard_text
    assert "body-completed" in guard_text
    for face in routed.exits:
        if "py.re_search" in str(face.guard):
            assert "match-pattern-face" in str(face.guard)


def test_finally_runs_on_consumed_unmet_and_retained_halt_paths():
    """Ordinary finally fans across consumed, ExpectationNotMet, and residual halt."""
    body, matching_effect, mismatch_effect = _multi_path_body()
    incoming = _boundary_exitset(body)
    routed, calls = _join_try_finally(incoming, ExitSet.completed("cleanup-done"))
    assert calls["n"] == 1

    consumed = [
        face
        for face in routed.exits
        if isinstance(face, Completed)
        and "match-none-face" in str(face.guard)
        and "body-matching" in str(face.guard)
        and _observed_binding(face) is not None
    ]
    assert consumed, routed.exits
    assert all(
        _observed_binding(face).effect is matching_effect for face in consumed
    )

    unmet = [
        face
        for face in routed.exits
        if isinstance(face, Halted)
        and isinstance(face.effect, ExpectationNotMetEffect)
        and "body-completed" in str(face.guard)
    ]
    assert unmet
    unmet_guards = " ".join(str(face.guard) for face in unmet)
    assert "match-none-face" in unmet_guards
    assert "match-pattern-face" in unmet_guards

    retained = [
        face
        for face in routed.exits
        if isinstance(face, Halted) and face.effect is mismatch_effect
    ]
    assert retained
    retained_guards = " ".join(str(face.guard) for face in retained)
    assert "match-none-face" in retained_guards
    assert "match-pattern-face" in retained_guards
    assert all(_observed_binding(face) is None for face in retained)
    assert all(_marker(face) == "mismatch" for face in retained)


def test_ordinary_cleanup_restores_incoming_result_and_state():
    """Restoring finally keeps consumed binding, unmet effect, and halt state."""
    body, matching_effect, mismatch_effect = _multi_path_body()
    incoming = _boundary_exitset(body)
    routed, _ = _join_try_finally(incoming, ExitSet.completed("cleanup-done"))

    for face in routed.exits:
        binding = _observed_binding(face)
        if binding is not None:
            assert binding.effect is matching_effect
            assert binding.effect.occurrence_id == "body.py:10:8:matching"

    for face in routed.exits:
        if isinstance(face, Halted) and isinstance(
            face.effect, ExpectationNotMetEffect
        ):
            assert _marker(face) == "completed-no-raise"

    for face in routed.exits:
        if isinstance(face, Halted) and face.effect is mismatch_effect:
            assert _marker(face) == "mismatch"
            assert face.state is not None
            assert "mismatch" in face.state.entries

    # Cleanup completion does not replace incoming faces with its own value.
    assert not any(
        isinstance(face, Completed) and face.value == "cleanup-done"
        for face in routed.exits
    )


def test_terminal_cleanup_overrides_incoming_faces():
    """Return-in-finally (cleanup_restores=False) supersedes every incoming face."""
    body, matching_effect, mismatch_effect = _multi_path_body()
    incoming = _boundary_exitset(body)
    terminal = ExitSet.completed("return-from-finally")
    routed, calls = _join_try_finally(incoming, terminal, restores=False)
    assert calls["n"] == 1
    assert routed.exits

    assert not any(
        isinstance(face, Halted) and face.effect is matching_effect
        for face in routed.exits
    )
    assert not any(
        isinstance(face, Halted) and face.effect is mismatch_effect
        for face in routed.exits
    )
    assert not any(
        isinstance(face, Halted) and isinstance(face.effect, ExpectationNotMetEffect)
        for face in routed.exits
    )
    assert all(isinstance(face, Completed) for face in routed.exits)
    assert all(face.value == "return-from-finally" for face in routed.exits)

    # Incoming face guards still ride the superseding completions.
    guard_text = " ".join(str(face.guard) for face in routed.exits)
    assert "match-none-face" in guard_text
    assert "match-pattern-face" in guard_text
    assert "body-matching" in guard_text
    assert "body-mismatch" in guard_text
    assert "body-completed" in guard_text


def test_excinfo_binds_only_consumed_occurrence_after_finally():
    """After restoring finally, only the matching raise binds excinfo."""
    body, matching_effect, mismatch_effect = _multi_path_body()
    incoming = _boundary_exitset(body)
    routed, _ = _join_try_finally(incoming, ExitSet.completed("cleanup-done"))

    bound = {
        _observed_binding(face).effect
        for face in routed.exits
        if _observed_binding(face) is not None
    }
    assert matching_effect in bound
    assert mismatch_effect not in bound
    assert all(
        effect is matching_effect and effect.occurrence_id == "body.py:10:8:matching"
        for effect in bound
    )
    for face in routed.exits:
        if isinstance(face, Halted):
            assert _observed_binding(face) is None


# ---------------------------------------------------------------------------
# Discrimination twins
# ---------------------------------------------------------------------------


def test_twin_none_vs_pattern_faces_survive_try_finally():
    """None/pattern twin: both face identities and distinct operands through try."""
    body, _, _ = _multi_path_body()
    pattern = SymbolicValue(make_var("twin_pattern"))
    boundary = _factored_boundary(body, pattern=pattern)
    guarded = boundary._guarded_semantics()
    assert {g.name for g, _ in guarded} == {
        "match-none-face",
        "match-pattern-face",
    }
    by_name = {g.name: s for g, s in guarded}
    assert isinstance(by_name["match-none-face"].message_pattern_operand, NoMessagePatternV1)
    assert isinstance(
        by_name["match-pattern-face"].message_pattern_operand,
        OptionalFormalArgumentProjectionV1,
    )

    routed, _ = _join_try_finally(
        boundary.desugar(), ExitSet.completed("cleanup-done")
    )
    text = " ".join(str(face.guard) for face in routed.exits)
    assert "match-none-face" in text and "match-pattern-face" in text
    for face in routed.exits:
        if "py.re_search" in str(face.guard):
            assert "match-pattern-face" in str(face.guard)


def test_twin_restoring_vs_overriding_cleanup():
    """Restoring finally keeps incoming; terminal finally overrides — twins."""
    body, matching_effect, mismatch_effect = _multi_path_body()
    incoming = _boundary_exitset(body)

    restored, _ = _join_try_finally(incoming, ExitSet.completed("cleanup-done"))
    assert any(
        isinstance(face, Halted) and face.effect is mismatch_effect
        for face in restored.exits
    )
    assert any(
        isinstance(face, Halted) and isinstance(face.effect, ExpectationNotMetEffect)
        for face in restored.exits
    )
    assert any(
        isinstance(face, Completed) and _observed_binding(face) is not None
        for face in restored.exits
    )

    overridden, _ = _join_try_finally(
        incoming, ExitSet.completed("return-from-finally"), restores=False
    )
    assert all(isinstance(face, Completed) for face in overridden.exits)
    assert all(face.value == "return-from-finally" for face in overridden.exits)
    assert not any(_observed_binding(face) for face in overridden.exits)
    assert any(
        isinstance(face, Halted) and face.effect is mismatch_effect
        for face in restored.exits
    )
    assert not any(
        isinstance(face, Halted) and face.effect is mismatch_effect
        for face in overridden.exits
    )


def test_pattern_complement_retained_halt_still_gets_finally():
    """Open pattern: held binds, complement halt unbound; both go through finally."""
    body, matching_effect, _ = _multi_path_body()
    pattern = SymbolicValue(make_var("open_msg"))
    incoming = _boundary_exitset(body, pattern=pattern)
    routed, calls = _join_try_finally(incoming, ExitSet.completed("cleanup-done"))
    assert calls["n"] == 1

    pattern_matching = [
        face
        for face in routed.exits
        if "match-pattern-face" in str(face.guard)
        and "body-matching" in str(face.guard)
        and "py.re_search" in str(face.guard)
    ]
    assert {type(face).__name__ for face in pattern_matching} == {
        "Completed",
        "Halted",
    }, pattern_matching
    held = next(f for f in pattern_matching if isinstance(f, Completed))
    failed = next(f for f in pattern_matching if isinstance(f, Halted))
    assert _observed_binding(held) is not None
    assert _observed_binding(held).effect is matching_effect
    assert failed.effect is matching_effect
    assert _observed_binding(failed) is None
    assert _marker(failed) == "matching"
