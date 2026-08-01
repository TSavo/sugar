"""Completed-face warning observation twins for ``WithEffectBoundarySugar``."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sugar_lift_py_tests.context_manager_contract import (
    CallParameterV1,
    EffectBoundarySemanticsV1,
    ExpectsModeV1,
    FormalArgumentProjectionV1,
    ImportSignatureV2,
    NoDefaultV1,
    NoMessagePatternV1,
    OptionalFormalArgumentProjectionV1,
    PositionalOrKeywordV1,
    RaiseEffectKindV1,
    WarningEffectKindV1,
    WarningObservationBindingV1,
)
from sugar_lift_py_tests.effect import ExpectationNotMetEffect, RaiseEffect, WarningEffect
from sugar_lift_py_tests.floor import (
    BlockValue,
    CallSiteValue,
    NoneValue,
    StringValue,
    TermValue,
)
from sugar_lift_py_tests.floor.warning_observation_value import WarningObservationValue
from sugar_lift_py_tests.ir import PrimitiveSort, ctor, make_var, str_const
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.outcome.exit_set import Completed, ExitSet, Halted, true_guard
from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.with_effect_boundary_sugar import WithEffectBoundarySugar
from sugar_source_tree.panic import SugarNotWritten


class _Fixed(Sugar):
    def __init__(self, outcome):
        self.outcome = outcome

    def desugar(self, ctx=None):
        del ctx
        return self.outcome

    @classmethod
    def witnesses(cls):
        return ()


class _ExpectedCategory(TermValue):
    def exception_type_identity(self):
        return self.value


class _SymbolicPattern(StringValue):
    def to_term(self, *, owner):
        del owner
        return make_var("warning_pattern")


def _identity(name: str):
    # ``python:exception_type_identity`` -- the SAME term the raise/except
    # projection mints (``SourceUnit.exception_type_identity``) and the same one
    # ``project_warning_observation`` emits. These twins previously spelled a
    # ``python:warning_category_identity`` that exists at no revision outside
    # this file, so they were green against a vocabulary of their own making:
    # the production path could never have emitted the term under test.
    return ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const(name)],
    )


SEMANTICS = EffectBoundarySemanticsV1(
    ExpectsModeV1(),
    WarningEffectKindV1(),
    FormalArgumentProjectionV1(0),
    NoMessagePatternV1(),
    WarningObservationBindingV1(),
)


def _boundary(*entries, expected=None):
    if expected is None:
        expected = _ExpectedCategory(_identity("FutureWarning"))
    manager_value = CallSiteValue(
        target_name="scope",
        arg_values=(expected,),
        parameters=("expected",),
        term=ctor("call", []),
        body=None,
    )
    signature = ImportSignatureV2(
        (
            CallParameterV1(
                "expected",
                PrimitiveSort("Value"),
                PositionalOrKeywordV1(),
                True,
                NoDefaultV1(),
            ),
        )
    )
    return WithEffectBoundarySugar(
        manager=_Fixed(Complete(manager_value)),
        body=(_Fixed(Complete(BlockValue(tuple(entries)))),),
        semantics=SEMANTICS,
        contract_ref=SimpleNamespace(import_signature=signature),
        context_manager_edge=None,
        # Real blame coordinate: SugarNotWritten refuses blame=None.
        site="with_effect_boundary_warning:test",
    )


def _warning(name: str):
    return WarningObservationValue(
        WarningEffect(name, category_identity=_identity(name))
    )


def test_truthful_warning_observation_completes_and_is_consumed():
    routed = _boundary(_warning("FutureWarning")).desugar()
    assert len(routed.exits) == 1
    face = routed.exits[0]
    assert isinstance(face, Completed)
    assert not any(
        isinstance(entry, WarningObservationValue)
        for entry in face.value.entries
    )


def test_lying_warning_observation_fails_the_assertion():
    routed = _boundary(_warning("DeprecationWarning")).desugar()
    assert len(routed.exits) == 1
    face = routed.exits[0]
    assert isinstance(face, Halted)
    assert isinstance(face.effect, ExpectationNotMetEffect)


def test_multi_authenticated_warning_observations_are_not_a_decided_miss():
    """Cardinality ≠ 1 is sugar-not-written, never MatchDecided(False).

    pytest.warns is existential. Two authenticated observations are evidence
    nobody's multi-obs sugar has read yet. Fabricating ExpectationNotMetEffect
    from len(observations) alone is a decided miss outside the three-valued
    matcher — the lying twin of this package.
    """
    with pytest.raises(SugarNotWritten) as raised:
        _boundary(
            _warning("FutureWarning"), _warning("DeprecationWarning")
        ).desugar()
    gap = raised.value
    assert gap.owner == "WithEffectBoundarySugar.warning_observation"
    assert "2 authenticated warning observations" in gap.observed
    assert "exactly one" in gap.requested
    assert "cardinality" in gap.fix


def test_unresolved_completed_face_is_undecided_not_false():
    unresolved = CallSiteValue(
        target_name="f",
        arg_values=(),
        parameters=(),
        term=ctor("call", []),
        body=None,
    )
    with pytest.raises(SugarNotWritten) as raised:
        _boundary(unresolved).desugar()
    assert raised.value.owner == "WithEffectBoundarySugar.warning_observation"
    assert "unresolved" in raised.value.observed


def test_truthful_no_warning_contract_completes_over_multi_statement_body():
    routed = _boundary(TermValue(1), TermValue(2), expected=NoneValue()).desugar()
    assert len(routed.exits) == 1
    face = routed.exits[0]
    assert isinstance(face, Completed)
    assert face.value.entries == (TermValue(1), TermValue(2))


def test_warning_arriving_at_no_warning_contract_fails_assertion():
    routed = _boundary(_warning("FutureWarning"), expected=NoneValue()).desugar()
    assert len(routed.exits) == 1
    face = routed.exits[0]
    assert isinstance(face, Halted)
    assert isinstance(face.effect, ExpectationNotMetEffect)


def test_no_warning_contract_with_unresolved_producer_is_undecided():
    unresolved = CallSiteValue(
        target_name="f",
        arg_values=(),
        parameters=(),
        term=ctor("call", []),
        body=None,
    )
    with pytest.raises(SugarNotWritten) as raised:
        _boundary(unresolved, expected=NoneValue()).desugar()
    assert raised.value.owner == "WithEffectBoundarySugar.warning_observation"
    assert raised.value.observed == "completed face has unresolved warning producers"


def test_two_no_warning_boundaries_do_not_share_observations():
    first = _boundary(TermValue("first"), expected=NoneValue()).desugar()
    second = _boundary(_warning("FutureWarning"), expected=NoneValue()).desugar()

    assert isinstance(first.exits[0], Completed)
    assert isinstance(second.exits[0], Halted)
    assert isinstance(second.exits[0].effect, ExpectationNotMetEffect)


def _no_warning_from_exitset(body_es):
    """``assert_produces_warning(None)`` over a pre-built body ExitSet.

    Used for exception-edge twins: the body already halted, and the temporal
    record rides on ``Halted.state`` exactly as ``reduce_block_to_exitset``
    leaves it.
    """
    manager_value = CallSiteValue(
        target_name="scope",
        arg_values=(NoneValue(),),
        parameters=("expected",),
        term=ctor("call", []),
        body=None,
    )
    signature = ImportSignatureV2(
        (
            CallParameterV1(
                "expected",
                PrimitiveSort("Value"),
                PositionalOrKeywordV1(),
                True,
                NoDefaultV1(),
            ),
        )
    )
    return WithEffectBoundarySugar(
        manager=_Fixed(Complete(manager_value)),
        body=(_Fixed(body_es),),
        semantics=SEMANTICS,
        contract_ref=SimpleNamespace(import_signature=signature),
        context_manager_edge=None,
        site="with_effect_boundary_warning:no_warning",
    )


def _raise_with_entries(*entries):
    """Exception edge: body statements then a real RaiseEffect halt."""
    type_identity = _identity("TypeError")
    raised_value = CallSiteValue(
        target_name="raised",
        arg_values=(StringValue("operand failed"),),
        parameters=("message",),
        term=ctor("call", []),
        body=None,
    )
    state = _ReducedBlock(
        entries=tuple(entries),
        can_fall_through=False,
        fall_through=(),
    )
    return ExitSet(
        (
            Halted(
                true_guard(),
                RaiseEffect(
                    exception_name="TypeError",
                    exception_type_coordinate=type_identity,
                    occurrence="body.py:3:4",
                    raised_value=raised_value,
                ),
                state,
            ),
        )
    )


def test_no_warning_exception_edge_without_warning_restores_the_halt():
    """Completed-edge inversion's exception twin: clean halt is not unmet."""
    routed = _no_warning_from_exitset(
        _raise_with_entries(TermValue(1), TermValue(2))
    ).desugar()
    assert len(routed.exits) == 1
    face = routed.exits[0]
    assert isinstance(face, Halted)
    assert isinstance(face.effect, RaiseEffect)
    assert face.effect.exception_name == "TypeError"
    # Absence decided without inventing a warning effect on the halt.
    assert not isinstance(face.effect, WarningEffect)


def test_no_warning_exception_edge_with_warning_fails_assertion():
    """Exception edge carries the observation on pre-halt state — still unmet."""
    routed = _no_warning_from_exitset(
        _raise_with_entries(_warning("FutureWarning"), TermValue(1))
    ).desugar()
    assert len(routed.exits) == 1
    face = routed.exits[0]
    assert isinstance(face, Halted)
    assert isinstance(face.effect, ExpectationNotMetEffect)
    # Failure is the assertion effect, never a fabricated WarningEffect halt.
    assert not isinstance(face.effect, WarningEffect)
    assert type(face.effect).__name__ == "ExpectationNotMetEffect"


def test_no_warning_exception_edge_with_unresolved_producer_is_undecided():
    unresolved = CallSiteValue(
        target_name="f",
        arg_values=(),
        parameters=(),
        term=ctor("call", []),
        body=None,
    )
    with pytest.raises(SugarNotWritten) as raised:
        _no_warning_from_exitset(_raise_with_entries(unresolved)).desugar()
    assert raised.value.owner == "WithEffectBoundarySugar.warning_observation"
    assert raised.value.observed == "completed face has unresolved warning producers"


def test_no_warning_both_edges_discriminate_absence_from_arrival():
    """One law, two edges: absence vs arrival must not collapse on either."""
    completed_absent = _boundary(TermValue("ok"), expected=NoneValue()).desugar()
    completed_arrived = _boundary(
        _warning("FutureWarning"), expected=NoneValue()
    ).desugar()
    exception_absent = _no_warning_from_exitset(
        _raise_with_entries(TermValue("ok"))
    ).desugar()
    exception_arrived = _no_warning_from_exitset(
        _raise_with_entries(_warning("FutureWarning"))
    ).desugar()

    assert isinstance(completed_absent.exits[0], Completed)
    assert isinstance(completed_arrived.exits[0], Halted)
    assert isinstance(completed_arrived.exits[0].effect, ExpectationNotMetEffect)

    assert isinstance(exception_absent.exits[0], Halted)
    assert isinstance(exception_absent.exits[0].effect, RaiseEffect)
    assert isinstance(exception_arrived.exits[0], Halted)
    assert isinstance(exception_arrived.exits[0].effect, ExpectationNotMetEffect)


def test_no_warning_empty_exit_set_cannot_pass_vacuously():
    """No faces means the body never resolved, not that no warning occurred."""
    with pytest.raises(SugarNotWritten) as raised:
        _no_warning_from_exitset(ExitSet(())).desugar()
    assert raised.value.owner == "WithEffectBoundarySugar.warning_observation"
    assert raised.value.observed == "body has no authenticated exit edge"


def test_no_warning_guarded_occurrence_is_undecided_on_exception_edge():
    """Guarded law is edge-independent: refuse on the halt face too."""
    guarded = WarningObservationValue(
        WarningEffect(
            "UserWarning",
            category_identity=_identity("UserWarning"),
        ),
        guards=(str_const("orient != tight"),),
    )
    with pytest.raises(SugarNotWritten) as raised:
        _no_warning_from_exitset(_raise_with_entries(guarded)).desugar()
    assert raised.value.owner == "WithEffectBoundarySugar.warning_observation"
    assert raised.value.observed == (
        "warning occurrence is reached only under a branch guard"
    )


WARNING_WITH_PATTERN = EffectBoundarySemanticsV1(
    ExpectsModeV1(),
    WarningEffectKindV1(),
    FormalArgumentProjectionV1(0),
    OptionalFormalArgumentProjectionV1(1),
    WarningObservationBindingV1(),
)

RAISE_WITH_PATTERN = EffectBoundarySemanticsV1(
    ExpectsModeV1(),
    RaiseEffectKindV1(),
    FormalArgumentProjectionV1(0),
    OptionalFormalArgumentProjectionV1(1),
    WarningObservationBindingV1(),
)


def _pattern_boundary(*, semantics, expected, pattern, body):
    manager_value = CallSiteValue(
        target_name="renamed_boundary",
        arg_values=(expected, pattern),
        parameters=("expected", "match"),
        term=ctor("call", []),
        body=None,
        keyword_names=("match",),
    )
    signature = ImportSignatureV2(
        (
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
                True,
                NoDefaultV1(),
            ),
        )
    )
    return WithEffectBoundarySugar(
        manager=_Fixed(Complete(manager_value)),
        body=body,
        semantics=semantics,
        contract_ref=SimpleNamespace(import_signature=signature),
        context_manager_edge=None,
        site="renamed.py:4:4",
    )


def _raise_after_warning(*, warning_message="deprecated operand"):
    type_identity = _identity("TypeError")
    raised_value = CallSiteValue(
        target_name="renamed_error",
        arg_values=(StringValue("unsupported operand type for &:"),),
        parameters=("message",),
        term=ctor("call", []),
        body=None,
    )
    state = _ReducedBlock(
        entries=(
            WarningObservationValue(
                WarningEffect(
                    "FutureWarning",
                    message=warning_message,
                    category_identity=_identity("FutureWarning"),
                )
            ),
        ),
        can_fall_through=False,
        fall_through=(),
    )
    return ExitSet(
        (
            Halted(
                true_guard(),
                RaiseEffect(
                    exception_name="TypeError",
                    exception_type_coordinate=type_identity,
                    occurrence="renamed.py:6:8",
                    raised_value=raised_value,
                ),
                state,
            ),
        )
    )


def _nested_assertion_boundaries(
    *, warning_pattern="deprecated", raise_pattern="unsupported operand type"
):
    inner = _pattern_boundary(
        semantics=WARNING_WITH_PATTERN,
        expected=_ExpectedCategory(_identity("FutureWarning")),
        pattern=StringValue(warning_pattern),
        body=(_Fixed(_raise_after_warning()),),
    )
    outer = _pattern_boundary(
        semantics=RAISE_WITH_PATTERN,
        expected=_ExpectedCategory(_identity("TypeError")),
        pattern=StringValue(raise_pattern),
        body=(inner,),
    )
    return inner, outer


def test_nested_warning_completion_reaches_outer_raise_boundary():
    """Truthful: the inner completed assertion exposes the original body halt."""
    _inner, outer = _nested_assertion_boundaries()
    routed = outer.desugar()
    assert len(routed.exits) == 1
    assert isinstance(routed.exits[0], Completed)


def test_nested_warning_lie_bites_before_outer_raise_can_consume():
    """Lying: a false inner warning assertion must not become outer success."""
    _inner, outer = _nested_assertion_boundaries(warning_pattern="never present")
    routed = outer.desugar()
    assert len(routed.exits) == 1
    face = routed.exits[0]
    assert isinstance(face, Halted)
    assert isinstance(face.effect, ExpectationNotMetEffect)


def test_symbolic_warning_pattern_retains_both_faces():
    """Undecided is neither success nor failure; both vendor faces survive."""
    inner = _pattern_boundary(
        semantics=WARNING_WITH_PATTERN,
        expected=_ExpectedCategory(_identity("FutureWarning")),
        pattern=_SymbolicPattern("diagnostic only"),
        body=(_Fixed(_raise_after_warning()),),
    )
    routed = inner.desugar()
    assert len(routed.exits) == 2
    assert all(isinstance(face, Halted) for face in routed.exits)
    assert {type(face.effect) for face in routed.exits} == {
        RaiseEffect,
        ExpectationNotMetEffect,
    }
