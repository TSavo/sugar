"""A halt of the With head's manager construction is the With's own face.

Python evaluates ``with <expr>:``'s context expression before anything is
entered. When constructing the manager may raise (pytest's
``AbstractRaises.__init__`` calls ``re.compile(match)``, an off-population
call that may raise), that raise leaves the With as itself: ``__enter__``,
the body and ``__exit__`` never run. An effect boundary over such a manager
is sealed from the completed construction faces alone and names the halts by
``SourceConstructorFacesCompletionV1`` on ``EffectBoundarySemanticsV1``; a
total construction encodes exactly as before, so its CIDs never move.
"""

from __future__ import annotations

import json

import pytest

from sugar_lift_py_tests.canonicalizer import encode_jcs
from sugar_lift_py_tests.context_manager_contract import (
    CallParameterV1,
    ContextManagerContractError,
    ImportSignatureV2,
    KeywordOnlyV1,
    LiteralDefaultV1,
    NoDefaultV1,
    PositionalOrKeywordV1,
    EffectBoundarySemanticsV1,
    ExceptionInfoBindingV1,
    ExpectsModeV1,
    FormalArgumentProjectionV1,
    OptionalFormalArgumentProjectionV1,
    RaiseEffectKindV1,
    SourceConstructorFacesCompletionV1,
    TotalCompletionV1,
    decode_context_manager_semantics_v1,
    semantics_to_value,
)
from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.ir import PrimitiveSort
from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.outcome import Completed, Halted, outcome_to_exitset

from test_sole_path_manager_construction import (
    _installed_pytest_raises_boundary,
    _negates_off_population_call,
)


def _boundary(construction):
    return EffectBoundarySemanticsV1(
        mode=ExpectsModeV1(),
        effect_kind=RaiseEffectKindV1(),
        expected_type_operand=FormalArgumentProjectionV1(0),
        message_pattern_operand=OptionalFormalArgumentProjectionV1(1),
        binding=ExceptionInfoBindingV1(),
        construction=construction,
    )


def _signature():
    return ImportSignatureV2(
        (
            CallParameterV1(
                "expected_exception",
                PrimitiveSort("Value"),
                PositionalOrKeywordV1(),
                True,
                NoDefaultV1(),
            ),
            CallParameterV1(
                "match",
                PrimitiveSort("String"),
                KeywordOnlyV1(),
                False,
                LiteralDefaultV1({"kind": "ctor", "name": "None", "args": []}),
            ),
        )
    )


def _wire(value):
    return json.loads(encode_jcs(semantics_to_value(value)))


def test_constructor_faces_round_trip_and_total_construction_is_absent():
    halting = _boundary(SourceConstructorFacesCompletionV1())
    wire = _wire(halting)
    assert wire["construction"] == {"kind": "source-constructor-faces"}
    assert decode_context_manager_semantics_v1(wire, _signature()) == halting
    total = _wire(_boundary(TotalCompletionV1()))
    # One theorem, one encoding: a total construction is the old wire.
    assert "construction" not in total
    assert decode_context_manager_semantics_v1(total, _signature()) == _boundary(
        TotalCompletionV1()
    )


@pytest.mark.parametrize(
    "construction",
    ({"kind": "total"}, {"kind": "source-enter-faces"}, "source-constructor-faces"),
)
def test_any_other_construction_testimony_is_refused(construction):
    wire = _wire(_boundary(SourceConstructorFacesCompletionV1()))
    wire["construction"] = construction
    with pytest.raises(ContextManagerContractError):
        decode_context_manager_semantics_v1(wire, _signature())


def _faces(tmp_path, body):
    boundary = _installed_pytest_raises_boundary(
        tmp_path, 'pytest.raises(ValueError, match="boom")', body
    )
    assert isinstance(boundary.semantics.construction, SourceConstructorFacesCompletionV1)
    return outcome_to_exitset(boundary.desugar()).exits


@pytest.mark.parametrize(
    "body",
    ('raise ValueError("boom")', "raise KeyError('k')", "pass"),
    ids=("absorbed", "propagated", "expectation-not-met"),
)
def test_a_construction_halt_never_enters_the_body_or_the_exit(tmp_path, body):
    faces = _faces(tmp_path, body)
    construction = [
        face
        for face in faces
        if _negates_off_population_call(face.guard, "python:re.compile")
    ]
    # Exactly pytest's construction outcomes, whatever the body does:
    # ``except re.error`` reaches ``fail(...)`` -- after formatting the
    # ``re.error`` into its message, which runs a ``__format__`` the lift does
    # not know is CPython's own and so may raise; anything else propagates.
    assert all(isinstance(face, Halted) for face in construction)
    (failed,) = [
        face
        for face in construction
        if isinstance(face.effect, RaiseEffect) and face.effect.exception_name == "Failed"
    ]
    others = sorted(
        face.effect.producer_node_owner
        for face in construction
        if isinstance(face.effect, UndeterminedRaiseEffect)
    )
    assert len(construction) == 3
    assert "re.error" in repr(failed.guard)
    assert others == ["BuiltinDunderCall:format", "OffPopulationCall:python:re.compile"]
    # Neither halt carries a body effect or an expectation verdict: nothing
    # was entered.
    body_faces = [face for face in faces if all(face is not c for c in construction)]
    assert body_faces
    # The boundary itself only exists where the construction completed.
    for face in body_faces:
        assert "python:off_population_call.completes" in repr(face.guard)


def test_the_boundary_verdicts_stand_on_the_completed_construction(tmp_path):
    seen = []

    def verdicts(body):
        rows = []
        root = tmp_path / str(len(seen))
        seen.append(body)
        root.mkdir()
        for face in _faces(root, body):
            if _negates_off_population_call(face.guard, "python:re.compile"):
                continue
            rows.append(
                "completed"
                if isinstance(face, Completed)
                else type(face.effect).__name__
                + ":"
                + str(getattr(face.effect, "exception_name", None))
            )
        return sorted(rows)

    assert verdicts('raise ValueError("boom")') == ["completed"]
    assert verdicts("raise KeyError('k')") == ["RaiseEffect:KeyError"]
    assert verdicts("pass") == ["ExpectationNotMetEffect:None"]
