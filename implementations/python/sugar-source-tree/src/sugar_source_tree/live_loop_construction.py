"""Sole-path production of guarded LoopConstructionV1 post-bindings."""

from __future__ import annotations

from dataclasses import dataclass, replace

from sugar_lift_python_source.canonical import cid_of_json
from sugar_lift_py_tests.floor.branch_result_coordinate import branch_result_guard
from sugar_lift_py_tests.ir import and_, atomic, not_, or_, str_const
from sugar_lift_py_tests.loop_construction import (
    decode_loop_construction_v1,
    seal_binding_state_v1,
    seal_loop_record,
)

from .binding_provenance import _state_wire
from .binding_state import (
    BindingEntryV1,
    BindingMap,
    BindingStateWireGap,
    BoundBindingStateV1,
    ConstructedValueTestimonyV1,
    GuardedBinding,
    GuardedBindingStateV1,
    UnboundBinding,
    UnboundBindingStateV1,
    _constructed_preimage,
    branch_result_slot,
)


@dataclass(frozen=True)
class LiveLoopProjectionV1:
    statement: object
    bindings: BindingMap


@dataclass(frozen=True)
class LiveOutwardHaltedFaceV1:
    statement_sugar: object
    guard: object
    state: tuple[BindingEntryV1, ...]


def _formula_cid(formula) -> str:
    import json

    from sugar_lift_py_tests.canonicalizer import encode_jcs
    from sugar_lift_py_tests.ir import formula_to_value

    return cid_of_json(json.loads(encode_jcs(formula_to_value(formula))))


def _seal_runtime_state(state):
    """Seal ONE live BindingState into its authenticated SealedBindingStateV1.

    The single recursive projection for every runtime binding state, not a
    Node-only special case: a constructed Node mints its value testimony; an
    unbound name carries its cause; a branch-joined GuardedBinding recurses into
    both arms and pins them under the same branch-result guard the loop control
    faces use. A guarded arm's identity is the content CID of its own sealed
    state, so nested guards/joins address by construction.
    """
    from .nodes import Node

    if isinstance(state, Node):
        constructed = state.sugar()
        testimony = ConstructedValueTestimonyV1.mint(
            state.fragment, cid_of_json(_constructed_preimage(constructed))
        )
        return BoundBindingStateV1(testimony)
    if isinstance(state, UnboundBinding):
        return UnboundBindingStateV1(state.cause.seal().cid)
    if isinstance(state, GuardedBinding):
        # `site` is unused in the branch-result term (it carries only
        # `slot.slot_id`), so the guard formula CID matches the loop control
        # guard for the same slot; pass the slot itself as the site owner.
        guard_cid = _formula_cid(branch_result_guard(state.slot, state.slot))
        when_true = _seal_runtime_state(state.when_true)
        when_false = _seal_runtime_state(state.when_false)
        return GuardedBindingStateV1(
            guard_cid,
            cid_of_json(_state_wire(when_true)),
            cid_of_json(_state_wire(when_false)),
        )
    raise BindingStateWireGap(
        f"live loop state has no authenticated sealed projection: "
        f"{type(state).__name__}"
    )


def _testified(entry: BindingEntryV1) -> BindingEntryV1:
    if entry.constructed_value_testimony is not None:
        return entry
    if isinstance(entry.sealed_state, (UnboundBindingStateV1, GuardedBindingStateV1)):
        return entry
    return replace(entry, sealed_state=_seal_runtime_state(entry.state))


def _sealed_state(snapshot: tuple[BindingEntryV1, ...]):
    testified = tuple(_testified(entry) for entry in snapshot)
    raw = seal_binding_state_v1(tuple(entry.wire() for entry in testified))
    return raw, testified


def _combine(outer, inner):
    return inner if outer is None else and_([outer, inner])


def _control_guards(statements, scope, outer=None):
    """Return exact owned control guards, including outward halted faces."""
    from .nodes import Break, Continue, For, If, Raise, Return, While

    breaks = []
    continues = []
    halted = []
    current = dict(scope)
    for statement in statements:
        if isinstance(statement, Break):
            breaks.append(outer)
            continue
        if isinstance(statement, Continue):
            continues.append(outer)
            continue
        if isinstance(statement, (Return, Raise)):
            halted.append((statement, outer, current))
            continue
        if isinstance(statement, If):
            guard = branch_result_guard(
                branch_result_slot(statement.test), statement.test.fragment
            )
            b, c, h = _control_guards(
                statement.body, current, _combine(outer, guard)
            )
            breaks.extend(b)
            continues.extend(c)
            halted.extend(h)
            b, c, h = _control_guards(
                statement.orelse, current, _combine(outer, not_(guard))
            )
            breaks.extend(b)
            continues.extend(c)
            halted.extend(h)
        # A nested loop owns its control effects; its recurrence is constructed
        # independently and is not attributed to this target.
        if isinstance(statement, (For, While)):
            continue
        binding = statement.substitution_binding(current)
        if binding:
            binding = statement._binding_entries(binding, current)
            binding = statement.refine_binding_entries(binding, current)
            current.update(binding)
    return breaks, continues, halted


def _guard_union(guards, fallback):
    concrete = [guard for guard in guards if guard is not None]
    if any(guard is None for guard in guards):
        return fallback
    if not concrete:
        return None
    return concrete[0] if len(concrete) == 1 else or_(concrete)


def _make_loop_ref(loop, entry, completion_kind):
    from .backend import Leaf, materialize
    from .shadow import ShadowNode

    return materialize(
        loop.unit,
        ShadowNode(
            "LoopBindingRef",
            loop.span,
            (
                ("target_cid", Leaf(loop.owned_loop_target.target_cid)),
                ("binding_coordinate_cid", Leaf(entry.coordinate.cid)),
                ("completion_kind", Leaf(completion_kind)),
            ),
        ),
        loop.reporter,
    )


def _make_statement(loop, construction, binding_coordinate_cids, outward_faces):
    from .backend import Child, Leaf, materialize
    from .shadow import ShadowNode, _handle_of

    return materialize(
        loop.unit,
        ShadowNode(
            "LoopRecurrenceStatement",
            loop.span,
            (
                ("loop", Child(_handle_of(loop))),
                ("construction", Leaf(construction)),
                ("target_cid", Leaf(construction.target.target_cid)),
                ("binding_coordinate_cids", Leaf(binding_coordinate_cids)),
                ("outward_faces", Leaf(outward_faces)),
            ),
        ),
        loop.reporter,
    )


def _record(preimage, cid_field):
    return seal_loop_record(preimage, cid_field)


def construct_live_loop_recurrence(loop, scope: BindingMap) -> LiveLoopProjectionV1:
    """Construct, decode, project, then publish a loop's guarded post-state."""
    from .nodes import For, While
    from .loop_recurrence import project_loop_post_binding

    if not isinstance(loop, (For, While)) or loop.owned_loop_target is None:
        raise BindingStateWireGap("live loop producer requires an owned For/While")
    carried_names = tuple(
        sorted(
            name
            for name in For._stmts_bound_names((*loop.body, *loop.orelse))
            if isinstance(scope.get(name), BindingEntryV1)
        )
    )
    pre_entries = tuple(scope[name] for name in carried_names)
    pre_state, pre_runtime = _sealed_state(pre_entries)

    target = loop.owned_loop_target.wire()
    target_cid = target["targetCid"]
    true_guard = atomic(
        "python.loop.reachable", [str_const(target_cid)]
    )
    break_guards, continue_guards, halted_specs = _control_guards(
        loop.body, scope
    )
    break_guard = _guard_union(break_guards, true_guard)
    continue_guard = _guard_union(continue_guards, true_guard)

    if isinstance(loop, For):
        exhaustion_guard = atomic(
            "python.loop.exhausted", [str_const(target_cid)]
        )
        operation_kind = "ForNext"
    else:
        test_guard = branch_result_guard(branch_result_slot(loop.test), loop.test.fragment)
        exhaustion_guard = not_(test_guard)
        true_guard = test_guard
        operation_kind = "WhileTest"

    completed_specs = []
    if break_guard is not None:
        completed_specs.append(("BreakExit", break_guard))
    completed_specs.append(("BodyFallthrough", true_guard))
    completed_specs.append(("NormalExhaustion", exhaustion_guard))

    state_records = [pre_state]
    runtime_states = {pre_state["stateCid"]: pre_runtime}
    face_records = []
    face_snapshots = {}
    live_guards = {}
    for completion_kind, guard in completed_specs:
        projected_entries = tuple(
            replace(
                entry,
                state=_make_loop_ref(loop, entry, completion_kind),
                sealed_state=BoundBindingStateV1(None),
            )
            for entry in pre_entries
        )
        state_record, runtime_snapshot = _sealed_state(projected_entries)
        if all(
            prior["stateCid"] != state_record["stateCid"]
            for prior in state_records
        ):
            state_records.append(state_record)
        runtime_states[state_record["stateCid"]] = runtime_snapshot
        guard_cid = _formula_cid(guard)
        live_guards[guard_cid] = guard
        face = _record(
            {
                "kind": "loop-completed-face",
                "schemaVersion": "1",
                "targetCid": target_cid,
                "completionKind": completion_kind,
                "guardFormulaCid": guard_cid,
                "stateCid": state_record["stateCid"],
            },
            "completedFaceCid",
        )
        face_records.append(face)
        face_snapshots[completion_kind] = (face, state_record, runtime_snapshot)

    outward_faces = []
    outward_face_cids = []
    outward_records = []
    for statement, guard, halted_scope in halted_specs:
        live_guard = guard if guard is not None else true_guard
        projected_entries = tuple(
            replace(
                halted_scope.get(name, entry),
                coordinate=entry.coordinate,
                sealed_state=BoundBindingStateV1(None),
            )
            for name, entry in zip(carried_names, pre_entries, strict=True)
        )
        state_record, runtime_snapshot = _sealed_state(projected_entries)
        if all(
            prior["stateCid"] != state_record["stateCid"]
            for prior in state_records
        ):
            state_records.append(state_record)
        runtime_states[state_record["stateCid"]] = runtime_snapshot
        guard_cid = _formula_cid(live_guard)
        live_guards[guard_cid] = live_guard
        statement_sugar = statement.sugar()
        effect_cid = cid_of_json(_constructed_preimage(statement_sugar))
        face = _record(
            {
                "kind": "loop-outward-halted-face",
                "schemaVersion": "1",
                "targetCid": target_cid,
                "effectCid": effect_cid,
                "guardFormulaCid": guard_cid,
                "stateCid": state_record["stateCid"],
            },
            "outwardHaltedFaceCid",
        )
        outward_records.append(face)
        outward_face_cids.append(face["outwardHaltedFaceCid"])
        outward_faces.append(
            LiveOutwardHaltedFaceV1(statement_sugar, live_guard, runtime_snapshot)
        )

    body_face = face_snapshots["BodyFallthrough"][0]
    records = [*state_records, *face_records, *outward_records]
    body_exit_cid = cid_of_json(
        {"loopBodyExitSet": loop.body[0].fragment.seal().cid if loop.body else target_cid}
    )

    if isinstance(loop, For):
        binder = _record(
            {
                "kind": "loop-binder-transform", "schemaVersion": "1",
                "targetCid": target_cid, "inputStateCid": pre_state["stateCid"],
                "elementValueCid": cid_of_json({"iteratorElement": target_cid}),
                "outputStateCid": pre_state["stateCid"],
                "binderPatternConstructionCid": loop.target.fragment.seal().cid,
            }, "binderTransformCid"
        )
        iterator = _record(
            {
                "kind": "loop-iterator-testimony", "schemaVersion": "1",
                "targetCid": target_cid,
                "iterableValueConstructionCid": loop.iter.fragment.seal().cid,
                "iteratorConstructionCid": cid_of_json({"iterator": target_cid}),
                "nextOperationCid": cid_of_json({"next": target_cid}),
                "exhaustionOperationCid": cid_of_json({"exhaustion": target_cid}),
            }, "iteratorTestimonyCid"
        )
        operation = _record(
            {
                "kind": "for-operation", "schemaVersion": "1",
                "targetCid": target_cid,
                "nativeLoopTermCid": cid_of_json({"native": "python:for"}),
                "binderTransformCid": binder["binderTransformCid"],
                "iteratorTestimonyCid": iterator["iteratorTestimonyCid"],
            }, "operationCid"
        )
        successor_cid = binder["binderTransformCid"]
        records.extend((binder, iterator, operation))
    else:
        test_transform = _record(
            {
                "kind": "loop-test-transform", "schemaVersion": "1",
                "targetCid": target_cid, "inputStateCid": pre_state["stateCid"],
                "testValueConstructionCid": loop.test.fragment.seal().cid,
                "trueGuardFormulaCid": _formula_cid(true_guard),
                "falseGuardFormulaCid": _formula_cid(exhaustion_guard),
                "haltedFaceCids": [],
            }, "testTransformCid"
        )
        operation = _record(
            {
                "kind": "while-operation", "schemaVersion": "1",
                "targetCid": target_cid,
                "nativeLoopTermCid": cid_of_json({"native": "python:while"}),
                "testTransformCid": test_transform["testTransformCid"],
            }, "operationCid"
        )
        successor_cid = test_transform["testTransformCid"]
        records.extend((test_transform, operation))

    body = _record(
        {
            "kind": "loop-body-transform", "schemaVersion": "1",
            "targetCid": target_cid, "inputStateCid": pre_state["stateCid"],
            "binderTransformCid": successor_cid,
            "bodySourceFragmentCid": loop.fragment.seal().cid,
            "bodyExitTemplateCid": body_exit_cid,
        }, "bodyTransformCid"
    )
    latch = _record(
        {
            "kind": "loop-latch-obligation", "schemaVersion": "1",
            "targetCid": target_cid,
            "inputCompletedFaceCid": body_face["completedFaceCid"],
            "inputStateCid": body_face["stateCid"],
            "operationKind": operation_kind,
            "successorTransformCid": successor_cid,
        }, "latchObligationCid"
    )
    records.extend((body, latch))

    continue_obligations = []
    if continue_guard is not None:
        obligation = _record(
            {
                "kind": "loop-continue-latch-obligation", "schemaVersion": "1",
                "targetCid": target_cid,
                "continueEffectCid": cid_of_json({"continue": target_cid}),
                "inputHaltedFaceCid": cid_of_json({"continueFace": target_cid}),
                "inputStateCid": body_face["stateCid"],
                "successorTransformCid": successor_cid,
            }, "continueLatchObligationCid"
        )
        records.append(obligation)
        continue_obligations.append(obligation["continueLatchObligationCid"])

    break_obligations = []
    if "BreakExit" in face_snapshots:
        break_face = face_snapshots["BreakExit"][0]
        obligation = _record(
            {
                "kind": "loop-break-exit-obligation", "schemaVersion": "1",
                "targetCid": target_cid,
                "breakEffectCid": cid_of_json({"break": target_cid}),
                "inputHaltedFaceCid": cid_of_json({"breakFace": target_cid}),
                "outputCompletedFaceCid": break_face["completedFaceCid"],
            }, "breakExitObligationCid"
        )
        records.append(obligation)
        break_obligations.append(obligation["breakExitObligationCid"])

    exhaustion_face = face_snapshots["NormalExhaustion"][0]
    exhaustion = _record(
        {
            "kind": "loop-exhaustion-exit-obligation", "schemaVersion": "1",
            "targetCid": target_cid,
            "operationTestimonyCid": operation["operationCid"],
            "inputStateCid": pre_state["stateCid"],
            "outputCompletedFaceCid": exhaustion_face["completedFaceCid"],
        }, "exhaustionExitObligationCid"
    )
    records.append(exhaustion)

    post_exhaustion_face = face_snapshots["NormalExhaustion"]
    else_body_cid = None
    else_obligation_cid = None
    if loop.orelse:
        exhaustion_scope = dict(scope)
        exhaustion_runtime = face_snapshots["NormalExhaustion"][2]
        for name, entry in zip(carried_names, exhaustion_runtime, strict=True):
            exhaustion_scope[name] = entry
        _else_statements, _changed, else_net = loop._substitute_body_tracked(
            loop.orelse, exhaustion_scope
        )
        else_runtime = tuple(
            replace(else_net[name], coordinate=pre_entry.coordinate)
            for name, pre_entry in zip(carried_names, pre_entries, strict=True)
        )
        else_state, else_runtime = _sealed_state(else_runtime)
        if all(
            prior["stateCid"] != else_state["stateCid"]
            for prior in state_records
        ):
            state_records.append(else_state)
            records.append(else_state)
        runtime_states[else_state["stateCid"]] = else_runtime
        else_output = _record(
            {
                "kind": "loop-completed-face",
                "schemaVersion": "1",
                "targetCid": target_cid,
                "completionKind": "NormalExhaustion",
                "guardFormulaCid": _formula_cid(exhaustion_guard),
                "stateCid": else_state["stateCid"],
            },
            "completedFaceCid",
        )
        records.append(else_output)
        face_records.append(else_output)
        else_body = _record(
            {
                "kind": "loop-body-transform",
                "schemaVersion": "1",
                "targetCid": target_cid,
                "inputStateCid": exhaustion_face["stateCid"],
                "binderTransformCid": successor_cid,
                "bodySourceFragmentCid": loop.orelse[0].fragment.seal().cid,
                "bodyExitTemplateCid": cid_of_json(
                    {"loopElseExitSet": loop.orelse[0].fragment.seal().cid}
                ),
            },
            "bodyTransformCid",
        )
        records.append(else_body)
        else_obligation = _record(
            {
                "kind": "loop-else-exhaustion-obligation",
                "schemaVersion": "1",
                "targetCid": target_cid,
                "inputCompletedFaceCid": exhaustion_face["completedFaceCid"],
                "elseBodyTransformCid": else_body["bodyTransformCid"],
                "outputCompletedFaceCid": else_output["completedFaceCid"],
            },
            "elseExhaustionObligationCid",
        )
        records.append(else_obligation)
        post_exhaustion_face = (else_output, else_state, else_runtime)
        else_body_cid = else_body["bodyTransformCid"]
        else_obligation_cid = else_obligation["elseExhaustionObligationCid"]

    post_records = []
    completed_post_kinds = (
        ("BreakExit", "NormalExhaustion")
        if "BreakExit" in face_snapshots
        else ("NormalExhaustion",)
    )
    for completion_kind in completed_post_kinds:
        face, state_record, _snapshot = (
            post_exhaustion_face
            if completion_kind == "NormalExhaustion"
            else face_snapshots[completion_kind]
        )
        for entry in pre_entries:
            post = _record(
                {
                    "kind": "loop-post-binding", "schemaVersion": "1",
                    "targetCid": target_cid,
                    "bindingCoordinateCid": entry.coordinate.cid,
                    "incomingStateCid": pre_state["stateCid"],
                    "completedFaceCid": face["completedFaceCid"],
                    "projectedStateCid": state_record["stateCid"],
                }, "postBindingObligationCid"
            )
            records.append(post)
            post_records.append(post["postBindingObligationCid"])

    root = _record(
        {
            "kind": "loop-construction", "schemaVersion": "1",
            "target": target, "preStateCid": pre_state["stateCid"],
            "operation": operation, "bodyTransformCid": body["bodyTransformCid"],
            "bodyExitTemplateCid": body_exit_cid,
            "latchObligationCids": [latch["latchObligationCid"]],
            "continueLatchObligationCids": continue_obligations,
            "breakExitObligationCids": break_obligations,
            "exhaustionExitObligationCid": exhaustion["exhaustionExitObligationCid"],
            "elseBodyCid": else_body_cid,
            "elseExhaustionObligationCid": else_obligation_cid,
            "completedFaceCids": [face["completedFaceCid"] for face in face_records],
            "outwardHaltedFaceCids": outward_face_cids,
            "postBindingObligationCids": post_records,
        }, "loopConstructionCid"
    )
    construction = decode_loop_construction_v1({"root": root, "records": records})

    bindings = {}
    for name, entry in zip(carried_names, pre_entries, strict=True):
        projected = project_loop_post_binding(
            construction=construction,
            binding_coordinate=entry.coordinate,
            runtime_states=runtime_states,
            live_guards=live_guards,
        )
        bindings[name] = replace(entry, state=projected, sealed_state=None)
    return LiveLoopProjectionV1(
        _make_statement(
            loop,
            construction,
            tuple(entry.coordinate.cid for entry in pre_entries),
            tuple(outward_faces),
        ),
        bindings,
    )


__all__ = [
    "LiveLoopProjectionV1",
    "LiveOutwardHaltedFaceV1",
    "construct_live_loop_recurrence",
]
