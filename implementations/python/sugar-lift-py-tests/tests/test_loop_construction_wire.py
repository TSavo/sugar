from __future__ import annotations

import copy

import pytest

from sugar_lift_py_tests.canonicalizer import blake3_512_of, encode_jcs
from sugar_lift_py_tests.context_manager_contract import _json_value
from sugar_lift_py_tests.loop_construction import (
    LoopWireError,
    decode_binding_state_v1,
    decode_loop_construction_v1,
    mint_loop_target_coordinate_v1,
    seal_loop_record,
)


def _cid(value):
    return blake3_512_of(encode_jcs(_json_value(value)).encode())


def _seal(value, field):
    return {**value, field: _cid(value)}


def _reseal(value, field):
    preimage = {key: item for key, item in value.items() if key != field}
    value[field] = _cid(preimage)


def _unknown_operation(graph):
    graph["root"]["operation"]["kind"] = "future-operation"
    _reseal(graph["root"]["operation"], "operationCid")
    _reseal(graph["root"], "loopConstructionCid")


def _mutate_latch(graph, **changes):
    latch = next(
        record
        for record in graph["records"]
        if record["kind"] == "loop-latch-obligation"
    )
    old_cid = latch["latchObligationCid"]
    latch.update(changes)
    _reseal(latch, "latchObligationCid")
    graph["root"]["latchObligationCids"] = [
        latch["latchObligationCid"] if cid == old_cid else cid
        for cid in graph["root"]["latchObligationCids"]
    ]
    _reseal(graph["root"], "loopConstructionCid")


def _binding_entry(value, ordinal):
    source_cid = _cid({"source": "binding"})
    site = {
        "file": "arbitrary.py",
        "span": {"start": ordinal, "end": ordinal + 1},
        "source_cid": source_cid,
        "cid": _cid({"fragment": ordinal}),
    }
    coordinate = _seal(
        {
            "kind": "binding-coordinate",
            "schemaVersion": "1",
            "scopeOwnerCid": _cid({"scope": "arbitrary"}),
            "bindingSite": site,
            "projectionPath": ["target", ordinal],
        },
        "bindingCoordinateCid",
    )
    testimony = _seal(
        {
            "kind": "constructed-value-testimony",
            "schemaVersion": "1",
            "sourceFragmentCid": site["cid"],
            "semanticValueCid": _cid({"constructed": value}),
        },
        "constructedValueTestimonyCid",
    )
    return {
        "coordinate": coordinate,
        "state": {"kind": "bound", "testimony": testimony},
    }


def _sample_graph():
    source = {
        "sourceCid": _cid({"source": "arbitrary"}),
        "startLine": 3,
        "startCol": 4,
        "endLine": 7,
        "endCol": 12,
    }
    target = mint_loop_target_coordinate_v1("For", source).wire()
    target_cid = target["targetCid"]
    pre_entry = _binding_entry(1, 0)
    break_entry = _binding_entry(2, 0)
    binding_coordinate_cid = pre_entry["coordinate"]["bindingCoordinateCid"]
    value_cid = _cid({"constructed": 1})
    pre = _seal(
        {
            "kind": "binding-state",
            "schemaVersion": "1",
            "entries": [pre_entry],
        },
        "stateCid",
    )
    break_state = _seal(
        {
            "kind": "binding-state",
            "schemaVersion": "1",
            "entries": [break_entry],
        },
        "stateCid",
    )
    guard_cid = _cid({"guard": True})
    break_face = _seal(
        {
            "kind": "loop-completed-face",
            "schemaVersion": "1",
            "targetCid": target_cid,
            "completionKind": "BreakExit",
            "guardFormulaCid": guard_cid,
            "stateCid": break_state["stateCid"],
        },
        "completedFaceCid",
    )
    exhaustion_face = _seal(
        {
            "kind": "loop-completed-face",
            "schemaVersion": "1",
            "targetCid": target_cid,
            "completionKind": "NormalExhaustion",
            "guardFormulaCid": guard_cid,
            "stateCid": pre["stateCid"],
        },
        "completedFaceCid",
    )
    body_face = _seal(
        {
            "kind": "loop-completed-face",
            "schemaVersion": "1",
            "targetCid": target_cid,
            "completionKind": "BodyFallthrough",
            "guardFormulaCid": guard_cid,
            "stateCid": pre["stateCid"],
        },
        "completedFaceCid",
    )
    binder = _seal(
        {
            "kind": "loop-binder-transform",
            "schemaVersion": "1",
            "targetCid": target_cid,
            "inputStateCid": pre["stateCid"],
            "elementValueCid": value_cid,
            "outputStateCid": pre["stateCid"],
            "binderPatternConstructionCid": _cid({"pattern": "real-pattern"}),
        },
        "binderTransformCid",
    )
    body = _seal(
        {
            "kind": "loop-body-transform",
            "schemaVersion": "1",
            "targetCid": target_cid,
            "inputStateCid": pre["stateCid"],
            "binderTransformCid": binder["binderTransformCid"],
            "bodySourceFragmentCid": _cid({"body": "source"}),
            "bodyExitTemplateCid": _cid({"body": "exit-template"}),
        },
        "bodyTransformCid",
    )
    iterator = _seal(
        {
            "kind": "loop-iterator-testimony",
            "schemaVersion": "1",
            "targetCid": target_cid,
            "iterableValueConstructionCid": _cid({"iterable": "value"}),
            "iteratorConstructionCid": _cid({"iterator": "value"}),
            "nextOperationCid": _cid({"operation": "next"}),
            "exhaustionOperationCid": _cid({"operation": "exhaustion"}),
        },
        "iteratorTestimonyCid",
    )
    operation = _seal(
        {
            "kind": "for-operation",
            "schemaVersion": "1",
            "targetCid": target_cid,
            "nativeLoopTermCid": _cid({"name": "python:for"}),
            "binderTransformCid": binder["binderTransformCid"],
            "iteratorTestimonyCid": iterator["iteratorTestimonyCid"],
        },
        "operationCid",
    )
    latch = _seal(
        {
            "kind": "loop-latch-obligation",
            "schemaVersion": "1",
            "targetCid": target_cid,
            "inputCompletedFaceCid": body_face["completedFaceCid"],
            "inputStateCid": pre["stateCid"],
            "operationKind": "ForNext",
            "successorTransformCid": body["bodyTransformCid"],
        },
        "latchObligationCid",
    )
    break_effect_cid = _cid({"effect": "typed-break", "targetCid": target_cid})
    halted_face_cid = _cid({"halted": "break-face"})
    break_obligation = _seal(
        {
            "kind": "loop-break-exit-obligation",
            "schemaVersion": "1",
            "targetCid": target_cid,
            "breakEffectCid": break_effect_cid,
            "inputHaltedFaceCid": halted_face_cid,
            "outputCompletedFaceCid": break_face["completedFaceCid"],
        },
        "breakExitObligationCid",
    )
    exhaustion = _seal(
        {
            "kind": "loop-exhaustion-exit-obligation",
            "schemaVersion": "1",
            "targetCid": target_cid,
            "operationTestimonyCid": iterator["iteratorTestimonyCid"],
            "inputStateCid": pre["stateCid"],
            "outputCompletedFaceCid": exhaustion_face["completedFaceCid"],
        },
        "exhaustionExitObligationCid",
    )
    post = _seal(
        {
            "kind": "loop-post-binding",
            "schemaVersion": "1",
            "targetCid": target_cid,
            "bindingCoordinateCid": binding_coordinate_cid,
            "incomingStateCid": pre["stateCid"],
            "completedFaceCid": break_face["completedFaceCid"],
            "projectedStateCid": break_state["stateCid"],
        },
        "postBindingObligationCid",
    )
    loop = _seal(
        {
            "kind": "loop-construction",
            "schemaVersion": "1",
            "target": target,
            "preStateCid": pre["stateCid"],
            "operation": operation,
            "bodyTransformCid": body["bodyTransformCid"],
            "bodyExitTemplateCid": body["bodyExitTemplateCid"],
            "latchObligationCids": [latch["latchObligationCid"]],
            "continueLatchObligationCids": [],
            "breakExitObligationCids": [break_obligation["breakExitObligationCid"]],
            "exhaustionExitObligationCid": exhaustion["exhaustionExitObligationCid"],
            "elseBodyCid": None,
            "elseExhaustionObligationCid": None,
            "completedFaceCids": [
                break_face["completedFaceCid"],
                body_face["completedFaceCid"],
                exhaustion_face["completedFaceCid"],
            ],
            "outwardHaltedFaceCids": [],
            "postBindingObligationCids": [post["postBindingObligationCid"]],
        },
        "loopConstructionCid",
    )
    records = [
        pre,
        break_state,
        break_face,
        body_face,
        exhaustion_face,
        binder,
        body,
        iterator,
        operation,
        latch,
        break_obligation,
        exhaustion,
        post,
    ]
    return {"root": loop, "records": records}


def test_binding_state_is_content_addressed_and_ordered():
    graph = _sample_graph()
    state = graph["records"][0]
    decoded = decode_binding_state_v1(state)
    assert decoded.state_cid == state["stateCid"]
    stale = copy.deepcopy(state)
    stale["entries"][0]["state"]["testimony"]["semanticValueCid"] = _cid(
        {"different": 1}
    )
    _reseal(
        stale["entries"][0]["state"]["testimony"],
        "constructedValueTestimonyCid",
    )
    with pytest.raises(LoopWireError, match="stateCid mismatch"):
        decode_binding_state_v1(stale)


def test_loop_target_is_content_addressed_without_self_hashing():
    graph = _sample_graph()
    target = graph["root"]["target"]
    assert "targetCid" not in {
        key: value for key, value in target.items() if key != "targetCid"
    }
    assert target["targetCid"] == _cid(
        {key: value for key, value in target.items() if key != "targetCid"}
    )


def test_loop_graph_round_trips_and_validates_every_child():
    graph = _sample_graph()
    decoded = decode_loop_construction_v1(graph)
    assert decoded.loop_construction_cid == graph["root"]["loopConstructionCid"]
    assert decoded.operation.kind == "for-operation"
    assert {face.completion_kind for face in decoded.completed_faces} == {
        "BodyFallthrough",
        "BreakExit",
        "NormalExhaustion",
    }
    assert decoded.wire_graph() == graph


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda graph: graph["root"].update(loopConstructionCid=_cid({"stale": 1})),
            "loopConstructionCid mismatch",
        ),
        (_unknown_operation, "unknown loop record kind"),
        (
            lambda graph: _mutate_latch(graph, operationKind="FutureLatch"),
            "unknown latch operation",
        ),
        (
            lambda graph: _mutate_latch(graph, inputStateCid=_cid({"missing": 1})),
            "missing binding-state",
        ),
    ],
)
def test_malformed_or_unknown_loop_wire_is_loud(mutation, message):
    graph = _sample_graph()
    mutation(graph)
    with pytest.raises(LoopWireError, match=message):
        decode_loop_construction_v1(graph)


def test_seal_loop_record_excludes_own_cid_and_rejects_existing_self_hash():
    preimage = {"kind": "example", "schemaVersion": "1", "value": 3}
    sealed = seal_loop_record(preimage, "exampleCid")
    assert sealed["exampleCid"] == _cid(preimage)
    with pytest.raises(LoopWireError, match="must not contain its own CID"):
        seal_loop_record(sealed, "exampleCid")
