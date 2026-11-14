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
from sugar_lift_py_tests.ir import PrimitiveSort


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
