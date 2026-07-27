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
    PositionalOrKeywordV1,
    WarningEffectKindV1,
    WarningObservationBindingV1,
)
from sugar_lift_py_tests.effect import ExpectationNotMetEffect, WarningEffect
from sugar_lift_py_tests.floor import BlockValue, CallSiteValue, TermValue
from sugar_lift_py_tests.floor.warning_observation_value import WarningObservationValue
from sugar_lift_py_tests.ir import PrimitiveSort, ctor, str_const
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.outcome.exit_set import Completed, Halted
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


def _identity(name: str):
    return ctor("python:warning_category_identity", [str_const("builtins"), str_const(name)])


SEMANTICS = EffectBoundarySemanticsV1(
    ExpectsModeV1(),
    WarningEffectKindV1(),
    FormalArgumentProjectionV1(0),
    NoMessagePatternV1(),
    WarningObservationBindingV1(),
)


def _boundary(*entries):
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
        site=None,
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


def test_matching_warning_plus_extra_warning_fails_the_assertion():
    routed = _boundary(
        _warning("FutureWarning"), _warning("DeprecationWarning")
    ).desugar()
    assert len(routed.exits) == 1
    face = routed.exits[0]
    assert isinstance(face, Halted)
    assert isinstance(face.effect, ExpectationNotMetEffect)


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
