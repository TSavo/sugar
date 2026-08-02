"""Project constructed source-manager testimony into the closed CM schema."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Literal

from sugar_lift_py_tests.canonicalizer import encode_jcs
from sugar_lift_py_tests.context_manager_contract import (
    CallParameterV1,
    ContextManagerSemanticsV1,
    EffectBoundarySemanticsV1,
    EnterResultContractV1,
    ExceptionInfoBindingV1,
    ExpectsModeV1,
    ExitContractV1,
    FormalArgumentProjectionV1,
    ImportSignatureV2,
    KeywordOnlyV1,
    LiteralDefaultV1,
    NeverSuppressesDispositionV1,
    NoDefaultV1,
    NoMessagePatternV1,
    OptionalFormalArgumentProjectionV1,
    PositionalOnlyV1,
    PositionalOrKeywordV1,
    ProtocolResourceSemanticsV1,
    RaiseEffectKindV1,
    ReturnTruthinessDispositionV1,
    SuppressesModeV1,
    VariadicKeywordV1,
    VariadicPositionalV1,
    semantics_to_value,
)
from sugar_lift_py_tests.floor import BlockValue, ReturnValue, TermValue
from sugar_lift_py_tests.ir import PrimitiveSort
from sugar_lift_py_tests.outcome import Complete, Completed, outcome_to_exitset

from .canonical import cid_of_json
from .manager_protocol_construction import (
    ConstructedManagerProtocolV1,
    GeneratorBackedManagerProtocolV1,
)


@dataclass(frozen=True)
class DerivedManagerSummaryV1:
    protocol_construction_cid: str
    enter_testimony_cid: str
    exit_testimony_cid: str
    semantics: ContextManagerSemanticsV1
    import_signature: ImportSignatureV2
    summary_cid: str

    @property
    def preimage(self):
        return {
            "kind": "source-derived-context-manager-summary",
            "schemaVersion": "1",
            "protocolConstructionCid": self.protocol_construction_cid,
            "enterTestimonyCid": self.enter_testimony_cid,
            "exitTestimonyCid": self.exit_testimony_cid,
            "semantics": json.loads(encode_jcs(semantics_to_value(self.semantics))),
            "importSignature": json.loads(
                encode_jcs(_signature_to_value(self.import_signature))
            ),
        }

    def __post_init__(self) -> None:
        if cid_of_json(self.preimage) != self.summary_cid:
            raise ValueError("derived manager summary CID does not match its preimage")


@dataclass(frozen=True)
class DerivedManagerSummaryGapV1:
    kind: Literal[
        "enter-may-halt",
        "exit-may-halt",
        "opaque-exit-truthiness",
    ]
    protocol_construction_cid: str
    detail: str


@dataclass(frozen=True)
class GeneratorEnterHaltFaceV1:
    """Guarded pre-yield exceptional enter halt of a generator CM.

    Derived from the authenticated generator body before the first yield —
    never from decorator/provider spelling. ``exception_type_source`` is the
    sealed source memento of the raise's exception expression; ``occurrence``
    is the raise statement's sealed fragment. Optional ``guard_source`` is the
    sealed if-test when the raise sits under a branch.
    """

    occurrence: dict
    exception_type_source: dict
    guard_source: dict | None
    cid: str

    @property
    def preimage(self) -> dict:
        return {
            "kind": "generator-enter-halt-face",
            "schemaVersion": "1",
            "occurrence": self.occurrence,
            "exceptionTypeSource": self.exception_type_source,
            "guardSource": self.guard_source,
        }

    def __post_init__(self) -> None:
        if cid_of_json(self.preimage) != self.cid:
            raise ValueError(
                "generator enter-halt face CID does not match its preimage"
            )

    @classmethod
    def mint(
        cls,
        *,
        occurrence: dict,
        exception_type_source: dict,
        guard_source: dict | None,
    ) -> "GeneratorEnterHaltFaceV1":
        preimage = {
            "kind": "generator-enter-halt-face",
            "schemaVersion": "1",
            "occurrence": occurrence,
            "exceptionTypeSource": exception_type_source,
            "guardSource": guard_source,
        }
        return cls(
            occurrence, exception_type_source, guard_source, cid_of_json(preimage)
        )


@dataclass(frozen=True)
class GeneratorYieldFaceV1:
    """Complementary yield face of generator enter (resource handoff).

    Distinct from enter-halt: this is the suspension that publishes the
    generator-backed resource, not an exceptional enter path.
    """

    occurrence: dict
    resource_source: dict | None
    cid: str

    @property
    def preimage(self) -> dict:
        return {
            "kind": "generator-yield-face",
            "schemaVersion": "1",
            "occurrence": self.occurrence,
            "resourceSource": self.resource_source,
        }

    def __post_init__(self) -> None:
        if cid_of_json(self.preimage) != self.cid:
            raise ValueError("generator yield face CID does not match its preimage")

    @classmethod
    def mint(
        cls, *, occurrence: dict, resource_source: dict | None
    ) -> "GeneratorYieldFaceV1":
        preimage = {
            "kind": "generator-yield-face",
            "schemaVersion": "1",
            "occurrence": occurrence,
            "resourceSource": resource_source,
        }
        return cls(occurrence, resource_source, cid_of_json(preimage))


@dataclass(frozen=True)
class GeneratorExitHaltFaceV1:
    """Post-yield exceptional exit of a generator CM.

    Distinct from enter-halt: temporal phase is post-yield (after resource
    handoff). Not a suppression result and not an enter failure. Optional
    ``guard_source`` distinguishes conditional exit faces without recombining.
    """

    occurrence: dict
    exception_type_source: dict
    guard_source: dict | None
    temporal_phase: Literal["post-yield"]
    cid: str

    @property
    def preimage(self) -> dict:
        return {
            "kind": "generator-exit-halt-face",
            "schemaVersion": "1",
            "occurrence": self.occurrence,
            "exceptionTypeSource": self.exception_type_source,
            "guardSource": self.guard_source,
            "temporalPhase": self.temporal_phase,
        }

    def __post_init__(self) -> None:
        if self.temporal_phase != "post-yield":
            raise ValueError(
                "generator exit-halt face temporal phase must be post-yield"
            )
        if cid_of_json(self.preimage) != self.cid:
            raise ValueError("generator exit-halt face CID does not match its preimage")

    @classmethod
    def mint(
        cls,
        *,
        occurrence: dict,
        exception_type_source: dict,
        guard_source: dict | None = None,
    ) -> "GeneratorExitHaltFaceV1":
        preimage = {
            "kind": "generator-exit-halt-face",
            "schemaVersion": "1",
            "occurrence": occurrence,
            "exceptionTypeSource": exception_type_source,
            "guardSource": guard_source,
            "temporalPhase": "post-yield",
        }
        return cls(
            occurrence,
            exception_type_source,
            guard_source,
            "post-yield",
            cid_of_json(preimage),
        )


@dataclass(frozen=True)
class GeneratorNestedManagerLayerV1:
    """One nested source-defined manager occurrence inside a generator CM body.

    Distinct occurrence identity from the outer protocol: the With site's sealed
    fragment CID plus nested protocol/frame construction CIDs. Temporal phase
    is pre-yield when the With sits before the outer yield (including
    ``with inner(): yield outer_resource``) and post-yield when it sits after.
    """

    occurrence: dict
    nested_protocol_construction_cid: str
    nested_generator_frame_cid: str
    temporal_phase: Literal["pre-yield", "post-yield"]
    cid: str
    nested_protocol: object = field(compare=False, repr=False, default=None)
    body_steps: tuple = field(compare=False, repr=False, default=())

    @property
    def preimage(self) -> dict:
        return {
            "kind": "generator-nested-manager-layer",
            "schemaVersion": "1",
            "occurrence": self.occurrence,
            "nestedProtocolConstructionCid": self.nested_protocol_construction_cid,
            "nestedGeneratorFrameCid": self.nested_generator_frame_cid,
            "temporalPhase": self.temporal_phase,
        }

    def __post_init__(self) -> None:
        if self.temporal_phase not in ("pre-yield", "post-yield"):
            raise ValueError("nested manager layer temporal phase invalid")
        if cid_of_json(self.preimage) != self.cid:
            raise ValueError(
                "generator nested manager layer CID does not match its preimage"
            )

    @classmethod
    def mint(
        cls,
        *,
        occurrence: dict,
        nested_protocol_construction_cid: str,
        nested_generator_frame_cid: str,
        temporal_phase: Literal["pre-yield", "post-yield"],
        nested_protocol: object = None,
        body_steps: tuple = (),
    ) -> "GeneratorNestedManagerLayerV1":
        preimage = {
            "kind": "generator-nested-manager-layer",
            "schemaVersion": "1",
            "occurrence": occurrence,
            "nestedProtocolConstructionCid": nested_protocol_construction_cid,
            "nestedGeneratorFrameCid": nested_generator_frame_cid,
            "temporalPhase": temporal_phase,
        }
        return cls(
            occurrence,
            nested_protocol_construction_cid,
            nested_generator_frame_cid,
            temporal_phase,
            cid_of_json(preimage),
            nested_protocol,
            body_steps,
        )


@dataclass(frozen=True)
class GeneratorBackedLifecycleProtocolV1(GeneratorBackedManagerProtocolV1):
    """Generator-backed protocol plus enter-halt / yield / exit-halt faces.

    **Is-a** :class:`GeneratorBackedManagerProtocolV1` — the closed protocol
    surface published on ``SourceDerivedGeneratorResourceRefV1``. Consumers
    read enter/exit definitions and lifecycle performance through that base
    type; they never branch on Lifecycle-vs-Manager wrapper spelling. Face
    fields are producer testimony; enter/exit performance inherit from base.
    Nested manager layers (With of source-defined managers inside the
    generator body) are additional testimony on the same surface.
    """

    enter_halt_faces: tuple[GeneratorEnterHaltFaceV1, ...] = ()
    yield_faces: tuple[GeneratorYieldFaceV1, ...] = ()
    exit_halt_faces: tuple[GeneratorExitHaltFaceV1, ...] = ()
    nested_manager_layers: tuple[GeneratorNestedManagerLayerV1, ...] = ()
    lifecycle_cid: str = ""

    def __post_init__(self) -> None:
        # Base protocol surface (frame, enter/exit defs, one-shot exit log).
        super().__post_init__()
        for face in self.enter_halt_faces:
            if face.cid != cid_of_json(face.preimage):
                raise ValueError("enter-halt face CID mismatch")
        for face in self.yield_faces:
            if face.cid != cid_of_json(face.preimage):
                raise ValueError("yield face CID mismatch")
        for face in self.exit_halt_faces:
            if face.cid != cid_of_json(face.preimage):
                raise ValueError("exit-halt face CID mismatch")
            if face.temporal_phase != "post-yield":
                raise ValueError("exit-halt face must be post-yield temporal phase")
        for layer in self.nested_manager_layers:
            if layer.cid != cid_of_json(layer.preimage):
                raise ValueError("nested manager layer CID mismatch")
        enter_cids = {face.cid for face in self.enter_halt_faces}
        exit_cids = {face.cid for face in self.exit_halt_faces}
        if enter_cids & exit_cids:
            raise ValueError("enter-halt and exit-halt faces must not share identity")
        layer_cids = [layer.cid for layer in self.nested_manager_layers]
        if len(layer_cids) != len(set(layer_cids)):
            raise ValueError("nested manager layers must have distinct identities")
        expected = cid_of_json(self.lifecycle_preimage)
        if self.lifecycle_cid and self.lifecycle_cid != expected:
            raise ValueError("generator lifecycle CID does not match its preimage")
        object.__setattr__(self, "lifecycle_cid", expected)

    @property
    def lifecycle_preimage(self) -> dict:
        return {
            "kind": "generator-backed-lifecycle-protocol",
            "schemaVersion": "1",
            "protocolConstructionCid": self.protocol_construction_cid,
            "generatorFrameCid": self.generator_frame_cid,
            "enterDefinition": self.enter_definition.wire(),
            "exitDefinition": self.exit_definition.wire(),
            "exitFaceId": self.exit_face_id,
            "enterHaltFaceCids": [face.cid for face in self.enter_halt_faces],
            "yieldFaceCids": [face.cid for face in self.yield_faces],
            "exitHaltFaceCids": [face.cid for face in self.exit_halt_faces],
            "nestedManagerLayerCids": [
                layer.cid for layer in self.nested_manager_layers
            ],
        }

    @classmethod
    def from_protocol(
        cls,
        protocol: GeneratorBackedManagerProtocolV1,
        *,
        enter_halt_faces: tuple[GeneratorEnterHaltFaceV1, ...] = (),
        yield_faces: tuple[GeneratorYieldFaceV1, ...] = (),
        exit_halt_faces: tuple[GeneratorExitHaltFaceV1, ...] = (),
        nested_manager_layers: tuple[GeneratorNestedManagerLayerV1, ...] = (),
    ) -> "GeneratorBackedLifecycleProtocolV1":
        return cls(
            protocol.protocol_construction_cid,
            protocol.generator_frame_cid,
            protocol.enter_definition,
            protocol.exit_definition,
            protocol.exit_face_id,
            protocol.generator_frame,
            enter_halt_faces,
            yield_faces,
            exit_halt_faces,
            nested_manager_layers,
            "",
        )


@dataclass(frozen=True)
class FactoredEffectBoundarySummaryV1:
    """Both message-pattern edges under their face guards.

    Undecided ``match`` stays partitioned:

    - ``match=None`` face → ``NoMessagePatternV1``
    - ``match=pattern`` face → pattern obligation

    as guarded alternatives. Faces are never recombined into one
    ``message_pattern_operand`` and never collapsed into a uniform sealed
    summary CID.
    """

    protocol_construction_cid: str
    enter_testimony_cid: str
    exit_testimony_cid: str
    boundary_faces: object
    import_signature: ImportSignatureV2


def derive_manager_summary(
    protocol: ConstructedManagerProtocolV1,
    *,
    behavior=None,
) -> (
    DerivedManagerSummaryV1
    | DerivedManagerSummaryGapV1
    | FactoredEffectBoundarySummaryV1
):
    """Derive only the theorem directly present in constructed outcomes.

    This first arm proves ``NeverSuppresses`` iff every enter face completes
    and every exit face completes with exact Python ``False`` or ``None``.
    Symbolic truthiness remains loud; it is never interpreted by target name.
    """
    from sugar_lift_py_tests.gap.panic import ConstructionPanic
    from sugar_lift_py_tests.outcome import ExitSet

    from sugar_source_tree.panic import OpaqueSourceCallResolutionGap, SugarNotWritten

    try:
        enter = outcome_to_exitset(protocol.enter_outcome())
    except ConstructionPanic as panic:
        owner = getattr(getattr(panic, "info", None), "owner", None) or "enter"
        observed = getattr(getattr(panic, "info", None), "observed", None) or str(panic)
        return DerivedManagerSummaryGapV1(
            "enter-may-halt",
            protocol.protocol_construction_cid,
            f"{owner}:{observed}",
        )
    except (OpaqueSourceCallResolutionGap, SugarNotWritten) as exc:
        owner = getattr(exc, "owner", None) or type(exc).__name__
        observed = getattr(exc, "observed", None) or str(exc)
        return DerivedManagerSummaryGapV1(
            "enter-may-halt",
            protocol.protocol_construction_cid,
            f"{owner}:{observed}",
        )
    if not enter.exits or any(not isinstance(face, Completed) for face in enter.exits):
        return DerivedManagerSummaryGapV1(
            "enter-may-halt", protocol.protocol_construction_cid, "__enter__ ExitSet"
        )
    try:
        exit_ = outcome_to_exitset(protocol.exit_outcome())
    except ConstructionPanic as panic:
        owner = getattr(getattr(panic, "info", None), "owner", None) or "exit"
        observed = getattr(getattr(panic, "info", None), "observed", None) or str(panic)
        sealed = _try_soft_effect_boundary_summary(protocol, behavior)
        if sealed is not None:
            return sealed
        return DerivedManagerSummaryGapV1(
            "exit-may-halt",
            protocol.protocol_construction_cid,
            f"{owner}:{observed}",
        )
    except (OpaqueSourceCallResolutionGap, SugarNotWritten) as exc:
        owner = getattr(exc, "owner", None) or type(exc).__name__
        observed = getattr(exc, "observed", None) or str(exc)
        sealed = _try_soft_effect_boundary_summary(protocol, behavior)
        if sealed is not None:
            return sealed
        return DerivedManagerSummaryGapV1(
            "exit-may-halt",
            protocol.protocol_construction_cid,
            f"{owner}:{observed}",
        )
    boundary = (
        _derive_effect_boundary(exit_, protocol, behavior)
        if behavior is not None
        else None
    )
    if boundary is not None:
        signature = _signature_for_behavior(behavior, boundary)
        return _sealed_summary(protocol, boundary, signature)
    # Non-total exit ExitSet (residual Halted faces, empty exits): formals may
    # still authenticate Expects/Raise. Soft sealing used to run only on
    # ConstructionPanic/SugarNotWritten; apply the same formal projection here
    # so message match formals seal OptionalFormalArgumentProjectionV1.
    if not exit_.exits or any(not isinstance(face, Completed) for face in exit_.exits):
        sealed = _try_soft_effect_boundary_summary(protocol, behavior)
        if sealed is not None:
            return sealed
        return DerivedManagerSummaryGapV1(
            "exit-may-halt", protocol.protocol_construction_cid, "__exit__ ExitSet"
        )
    disposition = (
        NeverSuppressesDispositionV1()
        if all(_exact_never_suppresses(face.value) for face in exit_.exits)
        else ReturnTruthinessDispositionV1()
    )
    semantics = ProtocolResourceSemanticsV1(
        EnterResultContractV1(PrimitiveSort("Value")),
        ExitContractV1(disposition),
    )
    signature = _signature_for_behavior(behavior, semantics)
    return _sealed_summary(protocol, semantics, signature)


def _sealed_summary(protocol, semantics, signature):
    preimage = {
        "kind": "source-derived-context-manager-summary",
        "schemaVersion": "1",
        "protocolConstructionCid": protocol.protocol_construction_cid,
        "enterTestimonyCid": protocol.enter_frame_cid,
        "exitTestimonyCid": protocol.exit_frame_cid,
        "semantics": json.loads(encode_jcs(semantics_to_value(semantics))),
        "importSignature": json.loads(encode_jcs(_signature_to_value(signature))),
    }
    return DerivedManagerSummaryV1(
        protocol.protocol_construction_cid,
        protocol.enter_frame_cid,
        protocol.exit_frame_cid,
        semantics,
        signature,
        cid_of_json(preimage),
    )


def _factored_effect_boundary_summary(protocol, boundary_faces, behavior):
    """Keep both message-pattern edges; do not seal a uniform summary."""
    signature = _signature_for_factored_boundaries(behavior, boundary_faces)
    return FactoredEffectBoundarySummaryV1(
        protocol.protocol_construction_cid,
        protocol.enter_frame_cid,
        protocol.exit_frame_cid,
        boundary_faces,
        signature,
    )


def _construct_message_pattern_operand(
    projected_match,
    *,
    site,
    construct_message_obligation,
):
    """Construct the message obligation on the source-authorized match face.

    ``match=None`` constructs ``NoMessagePatternV1`` without reading
    ``.pattern``. A source-written string formal is already the pattern
    obligation input — do not invent a ``.pattern`` attribute. Other non-None
    faces project ``.pattern`` then construct the regex obligation. Multi-face
    projections stay partitioned: each face keeps its own answer under its
    own guard.
    """
    from sugar_lift_py_tests.floor import NoneValue
    from sugar_lift_py_tests.floor.string_value import StringValue

    return projected_match.and_then(
        lambda match_value: (
            Complete(NoMessagePatternV1())
            if isinstance(match_value, NoneValue)
            else (
                construct_message_obligation(match_value)
                if isinstance(match_value, StringValue)
                else match_value.attribute("pattern", site).and_then(
                    construct_message_obligation
                )
            )
        )
    )


def _project_receiver_match(receiver, *, site):
    """Project only source-written receiver faces that carry ``match``."""
    from sugar_lift_py_tests.floor import ObjectValue, ReceiverStatePartitionValue
    from sugar_lift_py_tests.outcome import ExitSet

    if isinstance(receiver, ObjectValue):
        if not any(field.name == "match" for field in receiver.fields):
            return None
        return receiver.attribute("match", site)
    if not isinstance(receiver, ReceiverStatePartitionValue):
        return None
    projected = []
    for face in receiver.exits.exits:
        if not isinstance(face, Completed) or not isinstance(face.value, ObjectValue):
            continue
        if not any(field.name == "match" for field in face.value.fields):
            continue
        projected.extend(
            ExitSet((face,))
            .and_then(lambda value: value.attribute("match", site))
            .exits
        )
    return ExitSet(tuple(projected)) if projected else None


def _message_pattern_operand_faces(projected_operand):
    """Uniform faces collapse; non-uniform faces stay as both ExitSet edges.

    Identical completed answers may share one operand. Distinct answers —
    ``NoMessagePatternV1`` vs a pattern obligation — remain guarded
    alternatives. There is no gap and no silent pick-one summary.
    """
    from sugar_lift_py_tests.outcome import ExitSet

    projected = outcome_to_exitset(projected_operand)
    completed = tuple(face for face in projected.exits if isinstance(face, Completed))
    if not completed:
        return None
    if all(face.value == completed[0].value for face in completed):
        return completed[0].value
    return ExitSet(completed)


def _effect_boundary_for_message_operand(expected_index, message_operand):
    return EffectBoundarySemanticsV1(
        ExpectsModeV1(),
        RaiseEffectKindV1(),
        FormalArgumentProjectionV1(expected_index),
        message_operand,
        ExceptionInfoBindingV1(),
    )


# Authenticated message-pattern formal names. Used only as the soft-seal
# index when the call site supplied that formal — never as a manager spelling
# admission rule for which class is a CM.
_MESSAGE_FORMAL_NAMES = frozenset({"match", "message", "pattern", "msg"})


def _try_soft_effect_boundary_summary(protocol, behavior):
    """Apply formal soft-seal when exit theorem construction is incomplete.

    Shared by ConstructionPanic / SugarNotWritten arms and by a returned
    non-total ExitSet with residual Halted faces. Returns a sealed summary,
    a factored dual-face summary, a soft gap, or None when formals do not
    authenticate an expects-raise contract.
    """
    from sugar_lift_py_tests.gap.panic import ConstructionPanic
    from sugar_lift_py_tests.outcome import ExitSet

    from sugar_source_tree.panic import OpaqueSourceCallResolutionGap, SugarNotWritten

    try:
        soft = _soft_effect_boundary_from_exception_formals(
            behavior,
            protocol_construction_cid=protocol.protocol_construction_cid,
        )
    except (ConstructionPanic, OpaqueSourceCallResolutionGap, SugarNotWritten):
        # Soft projection of receiver match may still be unfinished; formals
        # that already authenticated type+string seal without that projection.
        return None
    if soft is None:
        return None
    if isinstance(soft, DerivedManagerSummaryGapV1):
        return soft
    if isinstance(soft, ExitSet):
        return _factored_effect_boundary_summary(protocol, soft, behavior)
    signature = _signature_for_behavior(behavior, soft)
    return _sealed_summary(protocol, soft, signature)


def _soft_effect_boundary_from_exception_formals(
    behavior,
    *,
    protocol_construction_cid,
):
    """Expects-mode EffectBoundary when exit body is undecided but formals decide.

    Installed-source ``pytest.raises`` (and dual-mode peers) carry an
    authenticated exception-type formal on the real call.  Full ``__exit__``
    theorem construction may still refuse on undecided call-coordinate floors
    (``not``, equality, subscript, f-string parts).  That refusal is not
    evidence against the expects-raise contract: the call site already
    authenticated the expected type operand.  Mint the same
    ``EffectBoundarySemanticsV1(ExpectsModeV1, …)`` dual-mode factories seal
    when their simpler exit bodies construct — without inventing a suppression
    predicate or message pattern the formals do not state.

    When receiver ``match`` faces disagree (None vs pattern), both EffectBoundary
    edges are emitted under their face guards. They are never recombined into
    one operand and never collapsed into a uniform sealed summary.
    """
    del protocol_construction_cid  # reserved for gap location; non-uniform is not a gap
    from sugar_lift_py_tests.outcome import ExitSet

    if behavior is None:
        return None
    actuals = tuple(getattr(behavior, "formal_actual_values", ()) or ())
    if not actuals:
        return None
    frame = getattr(behavior, "source_call_frame", None)
    parameters = tuple(getattr(frame, "parameters", ()) or ())
    expected_index = None
    message_index = None
    for index, value in enumerate(actuals):
        identity = getattr(value, "exception_type_identity", None)
        if callable(identity) and identity() is not None and expected_index is None:
            expected_index = index
            continue
        # Optional match= / message formal after the type:
        # 1. Ground StringValue (strongest)
        # 2. Bound message formal by authenticated parameter name even when
        #    the actual is still a Name/SymbolicValue at the use site
        #    (``pattern = 'needle'; match=pattern``). Explicit None stays
        #    NoMessagePattern.
        if expected_index is not None and message_index is None:
            from sugar_lift_py_tests.floor import NoneValue
            from sugar_lift_py_tests.floor.string_value import StringValue

            if isinstance(value, NoneValue):
                continue
            decided = getattr(value, "runtime_type_is_decided", None)
            if callable(decided) and decided() and isinstance(value, StringValue):
                message_index = index
                continue
            if index < len(parameters) and parameters[index] in _MESSAGE_FORMAL_NAMES:
                message_index = index
    if expected_index is None:
        return None
    message_operand = (
        NoMessagePatternV1()
        if message_index is None
        else OptionalFormalArgumentProjectionV1(message_index)
    )
    site = behavior.formal_actual_bindings[expected_index].coordinate
    projected_match = _project_receiver_match(behavior.receiver_state, site=site)
    if projected_match is not None:
        from sugar_lift_py_tests.gap.panic import ConstructionPanic

        from sugar_source_tree.panic import (
            OpaqueSourceCallResolutionGap,
            SugarNotWritten,
        )

        try:
            projected_operand = _construct_message_pattern_operand(
                projected_match,
                site=site,
                construct_message_obligation=lambda _pattern: Complete(message_operand),
            )
            resolved = _message_pattern_operand_faces(projected_operand)
        except (ConstructionPanic, OpaqueSourceCallResolutionGap, SugarNotWritten):
            # Receiver match projection may still be undecided; formals already
            # authenticated type + match index — seal from formals alone.
            resolved = None
        if resolved is None and message_index is None:
            return None
        if isinstance(resolved, ExitSet):
            return ExitSet(
                tuple(
                    Completed(
                        face.guard,
                        _effect_boundary_for_message_operand(
                            expected_index, face.value
                        ),
                        faces=face.faces,
                        pending_contracts=face.pending_contracts,
                    )
                    for face in resolved.exits
                    if isinstance(face, Completed)
                )
            )
        if resolved is not None:
            message_operand = resolved
    return _effect_boundary_for_message_operand(expected_index, message_operand)


def _signature_for_factored_boundaries(behavior, boundary_faces):
    """Signature for factored edges: include the message formal if any face needs it."""
    representative = None
    for face in boundary_faces.exits:
        if not isinstance(face, Completed):
            continue
        semantics = face.value
        if not isinstance(semantics, EffectBoundarySemanticsV1):
            continue
        if not isinstance(semantics.message_pattern_operand, NoMessagePatternV1):
            return _signature_for_behavior(behavior, semantics)
        if representative is None:
            representative = semantics
    return _signature_for_behavior(behavior, representative)


def _derive_effect_boundary(exit_set, protocol, behavior):
    from sugar_lift_py_tests.floor import BlockValue, BranchResultAuthentication
    from sugar_lift_py_tests.floor.predicate_value import PredicateValue
    from sugar_lift_py_tests.ir import _Atomic, _Connective, _Ctor
    from sugar_lift_py_tests.outcome import Halted

    predicates = []
    authentications = []
    for face in exit_set.exits:
        if not isinstance(face, Completed) or not isinstance(face.value, BlockValue):
            continue
        authentications.extend(
            item
            for item in face.value.statements
            if isinstance(item, BranchResultAuthentication)
        )
        if (
            face.value.statements
            and isinstance(face.value.statements[-1], ReturnValue)
            and isinstance(face.value.statements[-1].value, PredicateValue)
        ):
            predicates.append(face.value.statements[-1].value.formula)
    if predicates and all(predicate == predicates[0] for predicate in predicates[1:]):
        formula = predicates[0]
    else:
        formula = _guarded_literal_suppression_formula(exit_set)
    if formula is None:
        return None
    actuals = tuple(behavior.formal_actual_values)
    actual_terms = tuple(
        value.to_term(owner=behavior.resolved_object_cid) for value in actuals
    )
    expected_index = _formal_index_for_coordinate(
        formula, actual_terms, "python:exit_type"
    )
    if expected_index is None:
        return None
    message_index = _formal_index_for_coordinate(
        formula, actual_terms, "python:exit_value"
    )
    absent_effect_halts = tuple(
        face
        for face in exit_set.exits
        if isinstance(face, Halted)
        and any(
            _authentication_is_no_effect(item, protocol.exit_face_id)
            and _formula_mentions_branch_slot(face.guard, item.slot.slot_id)
            for item in authentications
        )
    )
    halted = tuple(face for face in exit_set.exits if isinstance(face, Halted))
    if any(face not in absent_effect_halts for face in halted):
        # A source-visible exit failure is not evidence that matching effects
        # are consumed.  It remains a protocol-construction gap until its own
        # outgoing face is represented by the summary schema.
        return None
    expects = bool(absent_effect_halts)
    return EffectBoundarySemanticsV1(
        ExpectsModeV1() if expects else SuppressesModeV1(),
        RaiseEffectKindV1(),
        FormalArgumentProjectionV1(expected_index),
        (
            NoMessagePatternV1()
            if message_index is None
            else OptionalFormalArgumentProjectionV1(message_index)
        ),
        ExceptionInfoBindingV1(),
    )


def _guarded_literal_suppression_formula(exit_set):
    """The suppression predicate of an exit that routes exact ``True``/``False``.

    A community effect boundary is rarely written as one returned predicate.
    It is written as a route:

        if <effect absent>:   raise ...
        if <matched>:         return True
        return False

    That is the same theorem as ``return <matched>`` with the partition moved
    from the value level to the GUARD level — the same move
    ``ExitSet.factor_completed`` makes for sequencing. The predicate is
    therefore the disjunction of the guards of the exact-``True`` faces.

    It is derived only when the completed face is TOTALLY classified:

    - every completed face is a block ending in ``return`` exact ``True`` or
      exact ``False`` — one unclassified face and the disjunction would speak
      for an outcome it does not cover, so the whole derivation refuses;
    - at least one ``True`` face exists — an empty disjunction is
      ``never suppresses``, which is a different contract and must not be
      fabricated here.

    Halted faces are the caller's business: it authenticates them separately
    and refuses any halt that is not a proven absent-effect halt.
    """
    from sugar_lift_py_tests.floor import (
        BlockValue,
        BranchResultAuthentication,
        GuardedReturn,
    )
    from sugar_lift_py_tests.ir import and_
    from sugar_lift_py_tests.outcome import Incomplete
    from sugar_lift_py_tests.outcome.exit_set import (
        _and_guards,
        _or_guards,
        false_guard,
    )

    authenticated = {}
    for face in exit_set.exits:
        block = getattr(face, "value", None)
        if not isinstance(block, BlockValue):
            continue
        for statement in block.statements:
            if isinstance(statement, BranchResultAuthentication):
                authenticated[statement.slot.slot_id] = statement.observed_guard

    formula = false_guard()
    saw_true = False
    for face in exit_set.exits:
        if not isinstance(face, Completed):
            continue
        block = face.value
        if not isinstance(block, BlockValue) or not block.statements:
            return None
        if block.can_fall_through:
            # An implicit ``None`` result is a third outcome this partition
            # does not classify. Refuse rather than let the disjunction speak
            # for it.
            return None
        for statement in block.statements:
            if isinstance(statement, Incomplete):
                return None
            if isinstance(statement, GuardedReturn):
                literal = _exact_bool_literal(statement.value)
                if literal is None:
                    return None
                if literal:
                    guards = tuple(statement.guards)
                    guard = guards[0] if len(guards) == 1 else and_(list(guards))
                    resolved = _resolve_branch_result_guards(
                        _and_guards(face.guard, guard), authenticated
                    )
                    if resolved is None:
                        return None
                    saw_true = True
                    formula = _or_guards(formula, resolved)
                continue
            if isinstance(statement, ReturnValue):
                literal = _exact_bool_literal(statement.value)
                if literal is None:
                    return None
                if literal:
                    resolved = _resolve_branch_result_guards(face.guard, authenticated)
                    if resolved is None:
                        return None
                    saw_true = True
                    formula = _or_guards(formula, resolved)
    return formula if saw_true else None


def _resolve_branch_result_guards(formula, authenticated):
    """Replace each branch-result slot literal by its AUTHENTICATED guard.

    A branch guard is spelled ``py.truthy(python:branch_result(<slot>))`` — an
    opaque coordinate. The block also carries a ``BranchResultAuthentication``
    proving that slot equivalent to the real observed comparison. Only that
    testimony may stand in for the slot; an unauthenticated slot returns
    ``None`` and the whole boundary stays loud rather than being read from a
    coordinate nobody proved anything about.
    """
    from sugar_lift_py_tests.ir import _Atomic, _Connective, _ConstStr, _Ctor

    if isinstance(formula, _Connective):
        operands = []
        for operand in formula.operands:
            resolved = _resolve_branch_result_guards(operand, authenticated)
            if resolved is None:
                return None
            operands.append(resolved)
        return type(formula)(formula.kind, tuple(operands))
    if not isinstance(formula, _Atomic) or formula.name != "py.truthy":
        return formula
    if len(formula.args) != 1:
        return formula
    term = formula.args[0]
    if not isinstance(term, _Ctor) or term.name != "python:branch_result":
        return formula
    if len(term.args) != 1 or not isinstance(term.args[0], _ConstStr):
        return None
    return authenticated.get(term.args[0].value)


def _exact_bool_literal(value: object) -> bool | None:
    """``True``/``False`` iff the value is exactly that literal; else ``None``.

    Never truthiness. A symbolic value, a name, or any non-``bool`` constant
    is unclassified and keeps the boundary loud.
    """
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
        FalseBoolLiteralSugar,
    )
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

    if isinstance(value, TrueBoolLiteralSugar):
        return True
    if isinstance(value, FalseBoolLiteralSugar):
        return False
    if isinstance(value, TermValue) and type(value.value) is bool:
        return value.value
    return None


def _formal_index_for_coordinate(formula, actual_terms, coordinate_name):
    from sugar_lift_py_tests.ir import _Atomic, _Connective

    candidates = set()
    pending = [formula]
    while pending:
        current = pending.pop()
        if isinstance(current, _Connective):
            pending.extend(current.operands)
            continue
        if not isinstance(current, _Atomic) or current.name not in {
            "eq",
            "py.eq",
            "identity",
            "python.subtype",
        }:
            continue
        if not any(_term_contains_ctor(arg, coordinate_name) for arg in current.args):
            continue
        for index, term in enumerate(actual_terms):
            if term in current.args:
                candidates.add(index)
    return next(iter(candidates)) if len(candidates) == 1 else None


def _term_contains_ctor(term, name):
    from sugar_lift_py_tests.ir import _Ctor

    return isinstance(term, _Ctor) and (
        term.name == name or any(_term_contains_ctor(arg, name) for arg in term.args)
    )


def _authentication_is_no_effect(authentication, exit_face_id):
    from sugar_lift_py_tests.ir import _Atomic, _Ctor

    guard = authentication.observed_guard
    if not isinstance(guard, _Atomic) or guard.name not in {"eq", "identity"}:
        return False
    return any(
        isinstance(arg, _Ctor)
        and arg.name == "python:exit_type"
        and arg.args
        and getattr(arg.args[0], "value", None) == exit_face_id
        for arg in guard.args
    ) and any(isinstance(arg, _Ctor) and arg.name == "None" for arg in guard.args)


def _formula_mentions_branch_slot(formula, slot_id):
    from sugar_lift_py_tests.ir import _Atomic, _Connective

    if isinstance(formula, _Connective):
        return any(
            _formula_mentions_branch_slot(item, slot_id) for item in formula.operands
        )
    return isinstance(formula, _Atomic) and any(
        _term_mentions_string(arg, slot_id) for arg in formula.args
    )


def _term_mentions_string(term, value):
    from sugar_lift_py_tests.ir import _Ctor

    return getattr(term, "value", None) == value or (
        isinstance(term, _Ctor)
        and any(_term_mentions_string(arg, value) for arg in term.args)
    )


def _signature_for_behavior(behavior, semantics):
    if behavior is None or behavior.source_call_frame is None:
        return ImportSignatureV2(())
    from sugar_lift_py_tests.ir import term_to_value

    frame = behavior.source_call_frame
    expected_index = (
        semantics.expected_type_operand.parameter_index
        if isinstance(semantics, EffectBoundarySemanticsV1)
        else None
    )
    message_index = (
        semantics.message_pattern_operand.parameter_index
        if isinstance(semantics, EffectBoundarySemanticsV1)
        and isinstance(
            semantics.message_pattern_operand, OptionalFormalArgumentProjectionV1
        )
        else None
    )
    passing_types = {
        "positional_only": PositionalOnlyV1,
        "positional_or_keyword": PositionalOrKeywordV1,
        "keyword_only": KeywordOnlyV1,
        "vararg": VariadicPositionalV1,
        "kwarg": VariadicKeywordV1,
    }
    parameters = []
    for index, (name, kind, default_sugar) in enumerate(
        zip(
            frame.parameters,
            frame.parameter_kinds,
            frame.default_sugars,
            strict=True,
        )
    ):
        variadic = kind in {"vararg", "kwarg"}
        default = NoDefaultV1()
        sort = PrimitiveSort("String" if index == message_index else "Value")
        if default_sugar is not None:
            from sugar_lift_py_tests.outcome import Complete

            outcome = default_sugar.desugar()
            if not isinstance(outcome, Complete):
                raise ValueError("source default did not construct completely")
            raw = json.loads(
                encode_jcs(term_to_value(outcome.value.to_term(owner=name)))
            )
            default = LiteralDefaultV1(raw)
            if raw.get("kind") == "const":
                sort = PrimitiveSort(raw["sort"]["name"])
        parameters.append(
            CallParameterV1(
                name,
                sort,
                passing_types[kind](),
                not variadic and default_sugar is None,
                default,
            )
        )
    return ImportSignatureV2(tuple(parameters))


def _signature_to_value(signature):
    from sugar_lift_py_tests.context_manager_contract import import_signature_to_value

    return import_signature_to_value(signature)


def _exact_never_suppresses(value: object) -> bool:
    from sugar_lift_py_tests.floor import GuardedReturn
    from sugar_lift_py_tests.outcome import Incomplete
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
        FalseBoolLiteralSugar,
    )
    from sugar_lift_py_tests.sugar.none_literal_sugar import NoneLiteralSugar

    if isinstance(value, BlockValue):
        if value.can_fall_through and not any(
            isinstance(entry, (ReturnValue, GuardedReturn, Incomplete))
            for entry in value.statements
        ):
            # A source-visible Python function that reaches the end returns
            # exact None.  The completed block is ordinary construction
            # testimony; rejecting embedded return/effect faces prevents a
            # fall-through face from speaking for a different guarded result.
            return True
        if not value.statements or not isinstance(value.statements[-1], ReturnValue):
            return False
        value = value.statements[-1].value
    if isinstance(value, (FalseBoolLiteralSugar, NoneLiteralSugar)):
        return True
    return isinstance(value, TermValue) and (
        value.value is None or type(value.value) is bool and value.value is False
    )


def _exception_class_testimony_or_absence(unit, node):
    """Project one exception ClassValue, or None when authority is unavailable.

    ``SourceUnit.exception_class_value`` raises ``SugarNotWritten`` when the
    identity has no closed authenticated class graph (opaque bases, no unique
    ClassDef, etc.). That is truthful absence for the optional class_value
    arm of exception-type formals — identity still seals without it.

    Only ``SugarNotWritten`` maps to absence. ``ConstructionPanic``, invariant
    errors, and unexpected runtime defects propagate: a broad ``except
    Exception`` would convert implementation failure into class_value=None and
    certify a lie.
    """
    from sugar_source_tree.panic import SugarNotWritten

    try:
        return unit.exception_class_value(node)
    except SugarNotWritten:
        return None


def populate_source_derived_resource_refs(
    source_file,
    *,
    root,
    path,
    distribution_index=None,
    artifact_graph_cache: dict | None = None,
    session=None,
    selected_coordinates: frozenset | None = None,
) -> None:
    """Preconstruct imported resource managers and freeze exact use-site rows.

    ``session`` owns every resolution memo for this population. Multi-resolve
    owners (file-open, package enumeration, census walk via ``walk_session_for``)
    must pass one shared session so export/frame amortization is real across
    receipts, consumer files, and same-content re-open under one workspace.

    Second open of the same content (after §4 SourceFile + lexical residency):
    prepare and lexical walks are free; this loop still re-seats into a fresh
    consumer ``construction_context``. Frame/export projection is free only
    when the same session is threaded (walk session). Live frame Nodes and
    protocol-bearing CM refs are session-bound — they must not be parked under
    a process-global content CID (same law as ``resolve_source_visible_frame``).
    Pure gap rows alone would be content-CID-able; they are not the residual wall.
    """
    from pathlib import Path

    from sugar_lift_py_tests.context_manager_resolution import (
        SourceDerivedContextManagerRefV1,
    )
    from sugar_lift_py_tests.import_binding import authenticated_import_use_receipts
    from sugar_lift_py_tests.ir import _term_content_cid
    from sugar_lift_py_tests.outcome import Complete
    from sugar_source_tree.binding_provenance import ConstructedValueTestimonyV1

    from .dependency_artifact import (
        ResolvedPythonObjectV1,
        resolve_import_binding,
    )
    from .manager_construction import (
        ConstructedCallActualV1,
        construct_manager_behavior,
    )
    from .manager_protocol_construction import construct_manager_protocol
    from .resolution_session import session_or_new

    # Multi-resolve owner entry: one session for every receipt in this loop.
    # Do not call session_or_new inside the receipt loop.
    session = session_or_new(session)
    # Population membrane: pin enrolls the consumer distribution (first path
    # segment under the locus root), not test-only deps (pytest) or stdlib.
    # Without this, one open of pandas/tests/io/json/test_pandas.py projected
    # 40 pytest frames (~3.8s) after the stdlib-only membrane.
    if session.enrolled_distributions is None:
        try:
            rel = Path(path).resolve().relative_to(Path(root).resolve())
            top = rel.parts[0] if rel.parts else None
        except ValueError:
            top = None
        if top and top.isidentifier() and top not in {"tests", "test", "src"}:
            session.enrolled_distributions = frozenset({top})
    context = source_file.root.unit.construction_context
    if context is None:
        return
    # Reuse the already-open typed module. A fresh lexical pass used to
    # MaterializeModule the consumer body a second time (same source_cid,
    # absolute vs relative seat in the profile) — residual ~0.25s on _json.
    receipts, _ = authenticated_import_use_receipts(
        Path(root),
        Path(path),
        source_file.unit.source,
        source_file.unit.source_cid,
        module_identities={},
        module=source_file.root,
    )
    uses = _projected_manager_call_uses(source_file)
    if selected_coordinates is not None:
        uses = {
            key: value
            for key, value in uses.items()
            if value[0] in selected_coordinates
        }
    graphs = {} if artifact_graph_cache is None else artifact_graph_cache
    # Seed from session so tops already resolved in frame/prefix projection
    # are not re-asked (warnings/re/inspect ×21 on test_pandas).
    if session.enabled:
        for top, graph in session.dependency_graphs.items():
            graphs.setdefault(top, graph)
    for receipt in receipts:
        raw_site = receipt.use["useSite"]
        key = (
            raw_site["startLine"],
            raw_site["startCol"],
            raw_site["endLine"],
            raw_site["endCol"],
        )
        selected = uses.get(key)
        if selected is None:
            continue
        coordinate, call, exit_face_id = selected
        top_level = receipt.target_symbol.removeprefix("python:").split(".", 1)[0]
        graph = graphs.get(top_level)
        if graph is None and session.enabled:
            graph = session.dependency_graphs.get(top_level)
            if graph is not None:
                graphs[top_level] = graph
        if graph is None:
            from .dependency_artifact import (
                DependencyArtifactAuthenticationError,
                authenticate_dependency_top_level,
            )

            try:
                graph = authenticate_dependency_top_level(
                    top_level, distribution_index=distribution_index
                )
            except DependencyArtifactAuthenticationError:
                _install_derivation_gap(
                    context, coordinate, receipt, "no-derived-contract"
                )
                continue
            graphs[top_level] = graph
            if session.enabled:
                session.dependency_graphs[top_level] = graph
        resolved = resolve_import_binding(receipt, graph=graph, session=session)
        if not isinstance(resolved, ResolvedPythonObjectV1):
            kind = getattr(resolved, "kind", None) or "no-derived-contract"
            _install_derivation_gap(context, coordinate, receipt, str(kind))
            continue
        # A source-owned suspension is already the native manager testimony
        # consumed by With._generator_manager_frame.  Install that exact frame
        # before attempting object-protocol derivation: forcing a generator
        # function's intentionally empty ordinary body only manufactures the
        # misleading residual ``non-manager-result:BlockValue``.  The generator
        # transition remains independently loud when its steps are opaque.
        from sugar_source_tree.panic import SugarNotWritten

        from .manager_construction import (
            ManagerConstructionGapV1,
            _install_source_call_frame,
            resolve_source_visible_frame,
        )

        # CITE, never abort: frame projection can SNW deep in a dependency
        # (decorated FunctionDef, incomplete body) OR TypeError on construction
        # (IfExpSugar body got SpreadCollectionSugar — #7062 second costume).
        # Failure already parks a gap; success must not discard the open's
        # function roster for the recensus.  One receipt's body gap is not the
        # enrolled file's zero. Named classes only — never bare except (panics
        # stay loud).
        try:
            frame_result = resolve_source_visible_frame(
                resolved,
                graph=graph,
                dependency_graphs=graphs,
                session=session,
            )
        except (SugarNotWritten, TypeError) as exc:
            kind, detail = _populate_body_defect_kind_detail(exc)
            _install_derivation_gap(
                context,
                coordinate,
                receipt,
                kind,
                detail,
            )
            continue
        if isinstance(frame_result, ManagerConstructionGapV1):
            # Membrane / export gap: cite the same way failure does.  Do NOT
            # fall through into construct_manager_behavior (that re-resolves
            # and re-MaterializeModule the dependency).
            kind, detail = _gap_kind_and_detail(frame_result)
            _install_derivation_gap(context, coordinate, receipt, kind, detail)
            continue
        frame, generator_target = frame_result
        if frame.generator_steps is not None:
            _install_source_call_frame(context, call, frame)
            # Seat the provider Call at the manager-use coordinate so a
            # bare-Name With head resolves through its reaching binding
            # rather than by spelling.  Direct Call heads already key the
            # frame by their own span; the use-site seat is what carries
            # assigned multi-manager projection.
            context.source_manager_provider_calls[coordinate] = call
            # Closed generator-backed resource contract: generator frame +
            # native enter/exit definitions → one typed source-derived ref.
            # Coordinates alone cannot construct the ref; non-generator
            # frames refuse. No ObjectValue fabrication.
            try:
                _publish_generator_backed_resource_contract(
                    context,
                    coordinate,
                    frame=frame,
                    generator_target=generator_target,
                    exit_face_id=exit_face_id,
                    receipt=receipt,
                    session=session,
                    graph=graph,
                    dependency_graphs=graphs,
                    distribution_index=distribution_index,
                    resolved_cid=resolved.cid,
                )
            except (SugarNotWritten, TypeError) as exc:
                kind, detail = _populate_body_defect_kind_detail(exc)
                _install_derivation_gap(
                    context,
                    coordinate,
                    receipt,
                    kind,
                    detail,
                )
            continue
        from sugar_lift_py_tests.context.reduce_context import ReduceContext
        from sugar_lift_py_tests.temporal import builtin_name_temporal

        actual_ctx = ReduceContext(temporal=builtin_name_temporal())
        # Formals whose role is an exception-type operand (raises / warn / external_error).
        _EXCEPTION_TYPE_FORMALS = frozenset(
            {
                "expected",
                "expected_exception",
                "expected_exceptions",
                "exception",
                "exc",
                "exc_type",
                "err_type",
                "category",
            }
        )
        frame_parameters = tuple(getattr(frame, "parameters", ()) or ())

        def _actual_outcome(node, *, formal_name: str | None = None):
            # Substitution has already replaced every reaching lexical binding.
            # A surviving bare builtin is therefore the language-owned value,
            # not a free formal. NameSugar deliberately represents every other
            # survivor symbolically, so project this one native floor here.
            #
            # Import Attribute exception-class paths (``pkg.Error``) and
            # provider-gated importorskip heads (``pa.ArrowInvalid``) seal
            # identity without Attribute floors inventing member success.
            from sugar_lift_py_tests.floor.authenticated_exception_type_value import (
                AuthenticatedExceptionTypeValue,
            )
            from sugar_lift_py_tests.floor.exception_class_value import (
                ExceptionClassValue,
            )
            from sugar_lift_py_tests.outcome import Complete as _Complete
            from sugar_lift_py_tests.sugar.authenticated_exception_type_sugar import (
                AuthenticatedExceptionTypeSugar,
            )
            from sugar_source_tree.nodes import Attribute, Name

            if isinstance(node, Name):
                builtin = actual_ctx.temporal.value_if_bound(node.id)
                if builtin is not None:
                    return _Complete(builtin)
            # Exception-type formals: seal import / provider-gated identity.
            if formal_name in _EXCEPTION_TYPE_FORMALS and isinstance(node, Name):
                identity = None
                mro = None
                class_value = None
                if isinstance(node, Name):
                    identity = node.unit.exception_type_identity(node)
                    if identity is None:
                        identity = node.unit.imported_exception_type_identity(node)
                    else:
                        mro = node.unit.exception_type_mro(node)
                        # Truthful absence vs loud defect: only SugarNotWritten
                        # is authority unavailable (class_value=None). Bugs and
                        # ConstructionPanic must not collapse to silent None.
                        class_value = _exception_class_testimony_or_absence(
                            node.unit, node
                        )
                if identity is not None:
                    return AuthenticatedExceptionTypeSugar(
                        node.sugar(),
                        identity,
                        mro,
                        site=node.fragment,
                        class_value=class_value,
                    ).desugar(actual_ctx)
            if isinstance(node, Attribute):
                from sugar_source_tree.panic import UnattributableRefusal

                from .external_exception_construction import (
                    ExternalExceptionConstructionGap,
                    construct_provider_exception_attribute,
                )

                try:
                    testimony = construct_provider_exception_attribute(
                        node,
                        root=Path(root),
                        path=Path(path),
                        graph_cache=graphs,
                        session=session,
                        distribution_index=distribution_index,
                    )
                except ExternalExceptionConstructionGap as exc:
                    raise UnattributableRefusal(
                        owner="provider_exception_type_construction",
                        blame=node.fragment,
                        observed=str(exc),
                        requested="provider-defined exception class testimony",
                        fix=(
                            "publish the named provider artifact source; never "
                            "replace it with an attribute spelling"
                        ),
                    ) from exc
                if testimony is not None:
                    class_value = testimony.class_value()
                    return _Complete(
                        AuthenticatedExceptionTypeValue(
                            class_value,
                            testimony.identity,
                            testimony.ancestry,
                            class_value,
                        )
                    )
                identity = node.unit.imported_exception_type_identity(node)
                if identity is not None:
                    qualified = getattr(identity.args[1], "value", None)
                    if isinstance(qualified, str) and qualified:
                        class_value = ExceptionClassValue(qualified)
                        return _Complete(
                            AuthenticatedExceptionTypeValue(
                                class_value, identity, None, class_value
                            )
                        )
            return node.sugar().desugar(actual_ctx)

        actuals = []
        for index, node in enumerate(call.args):
            formal_name = (
                frame_parameters[index] if index < len(frame_parameters) else None
            )
            outcome = _actual_outcome(node, formal_name=formal_name)
            if not isinstance(outcome, Complete):
                actuals = []
                break
            actuals.append(
                ConstructedCallActualV1(
                    node,
                    outcome.value,
                    ConstructedValueTestimonyV1.mint(
                        node.fragment,
                        _term_content_cid(outcome.value.to_term(owner=resolved.cid)),
                    ),
                )
            )
        keyword_actuals = []
        if len(actuals) == len(call.args):
            for keyword in call.keywords:
                if keyword.arg is None:
                    keyword_actuals = []
                    actuals = []
                    break
                outcome = _actual_outcome(keyword.value, formal_name=keyword.arg)
                if not isinstance(outcome, Complete):
                    keyword_actuals = []
                    actuals = []
                    break
                keyword_actuals.append(
                    (
                        keyword.arg,
                        ConstructedCallActualV1(
                            keyword.value,
                            outcome.value,
                            ConstructedValueTestimonyV1.mint(
                                keyword.value.fragment,
                                _term_content_cid(
                                    outcome.value.to_term(owner=resolved.cid)
                                ),
                            ),
                        ),
                    )
                )
        if len(actuals) != len(call.args):
            _install_derivation_gap(
                context, coordinate, receipt, "incomplete-call-actuals"
            )
            continue
        try:
            behavior = construct_manager_behavior(
                resolved,
                graph=graph,
                actuals=tuple(actuals),
                keyword_actuals=tuple(keyword_actuals),
                call_site=call.fragment,
                session=session,
            )
        except (SugarNotWritten, TypeError) as exc:
            kind, detail = _populate_body_defect_kind_detail(exc)
            _install_derivation_gap(
                context,
                coordinate,
                receipt,
                kind,
                detail,
            )
            continue
        from .manager_construction import ConstructedManagerBehaviorV1
        from .manager_protocol_construction import ConstructedManagerProtocolV1

        if not isinstance(behavior, ConstructedManagerBehaviorV1):
            # Stage-keyed residual — never collapse assertion-membrane mass into
            # a single opaque label, and never fuse the stage with its data:
            # `value-call-target` is the key, the callee names are the row.
            kind, detail = _gap_kind_and_detail(behavior)
            _install_derivation_gap(context, coordinate, receipt, kind, detail)
            continue
        try:
            protocol = construct_manager_protocol(behavior, exit_face_id=exit_face_id)
        except (SugarNotWritten, TypeError) as exc:
            kind, detail = _populate_body_defect_kind_detail(exc)
            _install_derivation_gap(
                context,
                coordinate,
                receipt,
                kind,
                detail,
            )
            continue
        if not isinstance(protocol, ConstructedManagerProtocolV1):
            kind, detail = _gap_kind_and_detail(protocol)
            _install_derivation_gap(context, coordinate, receipt, kind, detail)
            continue
        summary = derive_manager_summary(protocol, behavior=behavior)
        if isinstance(summary, FactoredEffectBoundarySummaryV1):
            # Both message-pattern edges stay published; never recombine and
            # never relabel as generic no-derived-contract.
            from sugar_lift_py_tests.context_manager_resolution import (
                FactoredSourceDerivedContextManagerRefV1,
            )

            context.source_derived_contract_refs[coordinate] = (
                FactoredSourceDerivedContextManagerRefV1(
                    coordinate,
                    summary.protocol_construction_cid,
                    summary.enter_testimony_cid,
                    summary.exit_testimony_cid,
                    summary.boundary_faces,
                    summary.import_signature,
                    protocol,
                )
            )
            continue
        if not isinstance(summary, DerivedManagerSummaryV1):
            kind, detail = _gap_kind_and_detail(summary)
            _install_derivation_gap(context, coordinate, receipt, kind, detail)
            continue
        # Publication: class-source __enter__/__exit__ definition coordinates
        # at the exact use-site receiver. Consumption reads them through
        # require_native_definition; this arm never looks them up later.
        _publish_class_protocol_native_definitions(context, coordinate, behavior)
        context.source_derived_contract_refs[coordinate] = (
            SourceDerivedContextManagerRefV1(
                coordinate,
                summary.summary_cid,
                summary.semantics,
                summary.import_signature,
                protocol,
            )
        )


def _publish_native_definition(context, receiver, slot, definition) -> None:
    """Enroll one authenticated definition coordinate into the shared door table.

    ``native_definitions`` is a mutable mapping held by the frozen
    ``ResolvedContractRefsV1``; publication is a transaction on that mapping
    only — never a second lookup path at desugar time.
    """
    from types import MappingProxyType

    from sugar_lift_py_tests.context_manager_resolution import (
        NativeProtocolSlot,
        ResolvedContractRefsV1,
        SourceFragmentCoordinateV1,
    )

    if not isinstance(slot, NativeProtocolSlot):
        raise TypeError("native protocol slot must be NativeProtocolSlot")
    if not isinstance(definition, SourceFragmentCoordinateV1):
        raise TypeError("native definition must be SourceFragmentCoordinateV1")
    refs = context.contract_refs
    table = refs.native_definitions
    if isinstance(table, MappingProxyType):
        # Frozen proxy (test fixtures / bound tables): rebuild the refs row.
        mutable = dict(table)
        mutable[(receiver, slot)] = definition
        object.__setattr__(
            context,
            "contract_refs",
            ResolvedContractRefsV1(
                refs.catalog_cid,
                refs.table_cid,
                refs.by_use_site,
                mutable,
            ),
        )
        return
    table[(receiver, slot)] = definition


def _publish_class_protocol_native_definitions(context, receiver, behavior) -> None:
    """Publish class-body ``__enter__`` / ``__exit__`` definition coordinates.

    Coordinates come from the constructed method frames' definition sites —
    the real FunctionDef spans — never from a manager name table.
    """
    from sugar_lift_py_tests.context_manager_resolution import NativeProtocolSlot

    from .manager_protocol_construction import _completed_object_receivers

    objects = _completed_object_receivers(behavior.receiver_state)
    if not objects:
        return
    enter = exit_ = None
    for method in objects[0].methods:
        frame = method.source_call_frame
        if frame is None:
            continue
        site = getattr(frame, "definition_site", None)
        if site is None:
            continue
        if method.name == "__enter__":
            enter = site
        elif method.name == "__exit__":
            exit_ = site
    if enter is None or exit_ is None:
        return
    if enter == exit_:
        # Distinct slots require distinct source definitions.
        return
    _publish_native_definition(
        context, receiver, NativeProtocolSlot.CONTEXT_ENTER, enter
    )
    _publish_native_definition(
        context, receiver, NativeProtocolSlot.CONTEXT_EXIT, exit_
    )


def _publish_generator_backed_resource_contract(
    context,
    receiver,
    *,
    frame,
    generator_target,
    exit_face_id,
    receipt,
    session,
    graph=None,
    dependency_graphs=None,
    distribution_index=None,
    resolved_cid: str,
) -> None:
    """Publish native enter/exit + one closed generator-backed resource ref.

    Requires authenticated generator lifecycle (frame.generator_steps) and
    decorator-constructed enter/exit definition coordinates. Installs
    ``SourceDerivedGeneratorResourceRefV1`` carrying generator protocol
    testimony — never a fabricated ObjectValue receiver.
    """
    from sugar_lift_py_tests.context_manager_contract import (
        EnterResultContractV1,
        ExitContractV1,
        ImportSignatureV2,
        ProtocolResourceSemanticsV1,
        ReturnTruthinessDispositionV1,
    )
    from sugar_lift_py_tests.context_manager_resolution import (
        NativeProtocolSlot,
        SourceDerivedGeneratorResourceRefV1,
    )
    from sugar_lift_py_tests.ir import PrimitiveSort

    from .manager_protocol_construction import (
        ManagerProtocolConstructionGapV1,
        construct_generator_backed_protocol,
    )

    coords = _protocol_coords_from_generator_decorators(
        generator_target,
        session=session,
        graph=graph,
        dependency_graphs=dependency_graphs,
        distribution_index=distribution_index,
    )
    if coords is None:
        _install_derivation_gap(
            context,
            receiver,
            receipt,
            "generator-protocol",
            "native enter/exit definition coordinates unavailable",
        )
        return
    enter, exit_ = coords
    _publish_native_definition(
        context, receiver, NativeProtocolSlot.CONTEXT_ENTER, enter
    )
    _publish_native_definition(
        context, receiver, NativeProtocolSlot.CONTEXT_EXIT, exit_
    )
    protocol = construct_generator_backed_protocol(
        frame=frame,
        enter_definition=enter,
        exit_definition=exit_,
        exit_face_id=exit_face_id,
        construction_cid=resolved_cid,
    )
    # Closed gap surface only — not an isinstance asker over protocol wrappers.
    gap = _generator_protocol_construction_gap(protocol)
    if gap is not None:
        kind, detail = _gap_kind_and_detail(gap)
        _install_derivation_gap(context, receiver, receipt, kind, detail)
        return
    enter_halts, yield_faces, exit_halts = _project_generator_lifecycle_faces(
        generator_target
    )
    nested_layers, nested_gap = _project_nested_manager_layers(
        generator_target,
        session=session,
        graph=graph,
        distribution_index=distribution_index,
        exit_face_id=exit_face_id,
    )
    if nested_gap is not None:
        kind, detail = nested_gap
        _install_derivation_gap(context, receiver, receipt, kind, detail)
        return
    # When nested layers resolve, rewrite Opaque With steps to NestedManagerStep
    # on a published frame (producer-owned; not a nodes.py emission edit).
    published_frame = _frame_with_nested_manager_steps(frame, nested_layers)
    if published_frame is not frame:
        protocol = construct_generator_backed_protocol(
            frame=published_frame,
            enter_definition=enter,
            exit_definition=exit_,
            exit_face_id=exit_face_id,
            construction_cid=resolved_cid,
        )
        gap = _generator_protocol_construction_gap(protocol)
        if gap is not None:
            kind, detail = _gap_kind_and_detail(gap)
            _install_derivation_gap(context, receiver, receipt, kind, detail)
            return
    # Lifecycle *is* the generator-backed protocol surface (subclass); it
    # publishes under SourceDerivedGeneratorResourceRefV1 without a second
    # isinstance filter over wrapper spelling.
    lifecycle = GeneratorBackedLifecycleProtocolV1.from_protocol(
        protocol,
        enter_halt_faces=enter_halts,
        yield_faces=yield_faces,
        exit_halt_faces=exit_halts,
        nested_manager_layers=nested_layers,
    )
    # Generator exit truthiness is the GCM throw/resume result — not a forged
    # NeverSuppresses theorem from an ObjectValue receiver.
    semantics = ProtocolResourceSemanticsV1(
        EnterResultContractV1(PrimitiveSort("Value")),
        ExitContractV1(ReturnTruthinessDispositionV1()),
    )
    signature = ImportSignatureV2(())
    summary_preimage = {
        "kind": "source-derived-generator-resource-summary",
        "schemaVersion": "1",
        "protocolConstructionCid": lifecycle.protocol_construction_cid,
        "generatorFrameCid": lifecycle.generator_frame_cid,
        "enterDefinition": enter.wire(),
        "exitDefinition": exit_.wire(),
        "enterHaltFaceCids": [face.cid for face in lifecycle.enter_halt_faces],
        "yieldFaceCids": [face.cid for face in lifecycle.yield_faces],
        "exitHaltFaceCids": [face.cid for face in lifecycle.exit_halt_faces],
        "nestedManagerLayerCids": [
            layer.cid for layer in lifecycle.nested_manager_layers
        ],
        "lifecycleCid": lifecycle.lifecycle_cid,
        "semantics": json.loads(encode_jcs(semantics_to_value(semantics))),
        "importSignature": json.loads(encode_jcs(_signature_to_value(signature))),
    }
    context.source_derived_contract_refs[receiver] = (
        SourceDerivedGeneratorResourceRefV1(
            receiver,
            cid_of_json(summary_preimage),
            semantics,
            signature,
            lifecycle,
        )
    )


def _generator_protocol_construction_gap(protocol):
    """Return a construction gap when ``construct_generator_backed_protocol`` refused.

    Closed gap surface: only the gap type is recognized. Success values are the
    protocol surface (base or lifecycle subclass) admitted by construction, not
    by an isinstance asker over wrapper spelling.
    """
    from .manager_protocol_construction import ManagerProtocolConstructionGapV1

    # type(protocol) is the closed door: gap class vs success protocol class.
    if type(protocol) is ManagerProtocolConstructionGapV1:
        return protocol
    return None


def _project_nested_manager_layers(
    generator_target,
    *,
    session,
    graph=None,
    distribution_index=None,
    exit_face_id: str,
) -> tuple[tuple[GeneratorNestedManagerLayerV1, ...], tuple[str, str] | None]:
    """Project With-of-source-defined-manager layers inside a generator body.

    Returns (layers, None) on success. When a nested With cannot honestly
    publish as a generator-backed protocol, returns
    ``((), ("nested-manager", detail))`` — a loud named gap, never a skip.
    Each layer also carries ``body_steps`` (peer of pre-yield Assign/If/Yield)
    for NestedManagerStep rewrite without nodes.py emission.
    """
    from sugar_source_tree.nodes import (
        Call,
        Expr,
        FunctionDef,
        If,
        Try,
        With,
        Yield,
    )

    from .manager_protocol_construction import construct_generator_backed_protocol

    if not isinstance(generator_target, FunctionDef):
        return (), None

    layers: list[GeneratorNestedManagerLayerV1] = []

    def visit(stmts, *, past: bool) -> tuple[str, str] | None:
        for statement in stmts:
            if isinstance(statement, Expr) and isinstance(statement.value, Yield):
                past = True
                continue
            if isinstance(statement, With):
                for item in statement.items:
                    expr = item.context_expr
                    if not isinstance(expr, Call):
                        # Non-Call With is not a nested generator manager layer.
                        continue
                    nested_fn = _resolve_nested_generator_function(
                        expr,
                        session=session,
                        graph=graph,
                        distribution_index=distribution_index,
                    )
                    if nested_fn is None:
                        # Not a resolvable source-defined manager — leave Opaque.
                        continue
                    nested_frame, nested_target = _source_visible_frame_for_function(
                        nested_fn
                    )
                    if nested_frame is None or nested_target is None:
                        continue
                    if getattr(nested_frame, "generator_steps", None) is None:
                        # Source function but not a generator CM — not our layer.
                        continue
                    # Recognized nested generator manager: must publish honestly
                    # or gap loud — never skip.
                    coords = _protocol_coords_from_generator_decorators(
                        nested_target,
                        session=session,
                        graph=graph,
                        distribution_index=distribution_index,
                    )
                    if coords is None:
                        return (
                            "nested-manager",
                            "nested manager native enter/exit definitions unavailable",
                        )
                    n_enter, n_exit = coords
                    nested_protocol = construct_generator_backed_protocol(
                        frame=nested_frame,
                        enter_definition=n_enter,
                        exit_definition=n_exit,
                        exit_face_id=(
                            f"{exit_face_id}:nested:"
                            f"{statement.fragment.seal().cid[:16]}"
                        ),
                        construction_cid=nested_frame.frame_cid,
                    )
                    if _generator_protocol_construction_gap(nested_protocol) is not None:
                        return (
                            "nested-manager",
                            "nested manager protocol construction refused",
                        )
                    body_steps = _nameable_nested_with_body_steps(statement.body)
                    if body_steps is None:
                        return (
                            "nested-manager",
                            "nested With body holds an unnameable statement",
                        )
                    phase: Literal["pre-yield", "post-yield"] = (
                        "post-yield" if past else "pre-yield"
                    )
                    # Occurrence identity is the With item's context expression
                    # fragment — distinct per nested Call, not the outer protocol.
                    item_cid = expr.fragment.seal().cid
                    occurrence = {
                        "kind": "generator-nested-with-occurrence",
                        "schemaVersion": "1",
                        "cid": item_cid,
                        "withCid": statement.fragment.seal().cid,
                    }
                    layers.append(
                        GeneratorNestedManagerLayerV1.mint(
                            occurrence=occurrence,
                            nested_protocol_construction_cid=(
                                nested_protocol.protocol_construction_cid
                            ),
                            nested_generator_frame_cid=nested_frame.frame_cid,
                            temporal_phase=phase,
                            nested_protocol=nested_protocol,
                            body_steps=body_steps,
                        )
                    )
                # Yield inside With body counts as past-yield for following stmts.
                if any(
                    isinstance(s, Expr) and isinstance(s.value, Yield)
                    for s in statement.body
                ):
                    past = True
                gap = visit(statement.body, past=past)
                if gap is not None:
                    return gap
                continue
            if isinstance(statement, If):
                gap = visit(statement.body, past=past)
                if gap is not None:
                    return gap
                gap = visit(statement.orelse, past=past)
                if gap is not None:
                    return gap
                continue
            if isinstance(statement, Try):
                gap = visit(statement.body, past=past)
                if gap is not None:
                    return gap
                for handler in statement.handlers:
                    gap = visit(handler.body, past=past)
                    if gap is not None:
                        return gap
                gap = visit(statement.orelse, past=past)
                if gap is not None:
                    return gap
                gap = visit(statement.finalbody, past=past)
                if gap is not None:
                    return gap
                continue
        return None

    gap = visit(generator_target.body, past=False)
    if gap is not None:
        return (), gap
    return tuple(layers), None


def _source_visible_frame_for_function(function_def):
    """Build (frame, FunctionDef) for a same-module generator FunctionDef."""
    from sugar_source_tree.nodes import FunctionDef

    if not isinstance(function_def, FunctionDef):
        return None, None
    frame = function_def.source_visible_call_frame()
    if frame is None:
        return None, None
    return frame, function_def


def _resolve_nested_generator_function(
    call, *, session, graph=None, distribution_index=None
):
    """Resolve Call.func to a same-module or imported FunctionDef when possible."""
    from sugar_source_tree.nodes import FunctionDef, ImportFrom, Name

    func = call.func
    if not isinstance(func, Name):
        return None
    binds = (func.unit.module_direct_bindings or {}).get(func.id, ())
    if len(binds) == 1 and isinstance(binds[0], FunctionDef):
        return binds[0]
    if len(binds) == 1 and isinstance(binds[0], ImportFrom):
        constructed = _construct_decorator_function(
            func,
            session=session,
            graph=graph,
            distribution_index=distribution_index,
        )
        if isinstance(constructed, FunctionDef):
            return constructed
    return None


def _nameable_nested_with_body_steps(body) -> tuple | None:
    """Name With-body steps under the merged pre-yield law (Assign/If/Yield peers).

    Returns None when any statement is unnameable — keeps the nested With loud.
    """
    from sugar_lift_py_tests.generator_construction import (
        AssignStepV1,
        IfStepV1,
        InertStepV1,
        ReturnStepV1,
        YieldStepV1,
    )
    from sugar_source_tree.nodes import (
        AnnAssign,
        Assign,
        Constant,
        Expr,
        If,
        Name,
        Pass,
        Return,
        Yield,
    )

    def name_one(statement):
        if isinstance(statement, Expr) and isinstance(statement.value, Yield):
            value = statement.value.value
            return YieldStepV1(None if value is None else value.sugar())
        if isinstance(statement, Return):
            return ReturnStepV1(
                None if statement.value is None else statement.value.sugar()
            )
        if (
            isinstance(statement, Expr)
            and isinstance(statement.value, Constant)
        ):
            return InertStepV1(statement.kind)
        if isinstance(statement, Pass):
            return InertStepV1(statement.kind)
        if (
            isinstance(statement, Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], Name)
        ):
            return AssignStepV1(
                statement.targets[0].id,
                statement.value.sugar(),
                statement.fragment.seal().cid,
            )
        if (
            isinstance(statement, AnnAssign)
            and isinstance(statement.target, Name)
            and statement.value is not None
        ):
            return AssignStepV1(
                statement.target.id,
                statement.value.sugar(),
                statement.fragment.seal().cid,
            )
        if isinstance(statement, If):
            then_b = name_body(statement.body)
            else_b = name_body(statement.orelse)
            if then_b is None or else_b is None:
                return None
            return IfStepV1(
                statement.test.sugar(),
                then_b,
                else_b,
                statement.fragment.seal().cid,
            )
        return None

    def name_body(stmts):
        out = []
        for s in stmts:
            named = name_one(s)
            if named is None:
                return None
            out.append(named)
        return tuple(out)

    return name_body(body)


def _frame_with_nested_manager_steps(frame, nested_layers: tuple):
    """Rewrite Opaque With steps to NestedManagerStepV1 when layers resolve.

    Producer-owned: does not edit nodes.py emission. Leaves the frame unchanged
    when there are no nested layers or no Opaque With to rewrite.
    """
    from types import SimpleNamespace

    from sugar_lift_py_tests.generator_construction import (
        NestedManagerStepV1,
        OpaqueStepV1,
    )

    if not nested_layers:
        return frame
    steps = getattr(frame, "generator_steps", None)
    if not steps:
        return frame
    rewritten = []
    layer_idx = 0
    for step in steps:
        if (
            isinstance(step, OpaqueStepV1)
            and step.observed == "With"
            and layer_idx < len(nested_layers)
        ):
            layer = nested_layers[layer_idx]
            layer_idx += 1
            nested_protocol = layer.nested_protocol
            if nested_protocol is None:
                rewritten.append(step)
                continue
            occurrence_cid = layer.occurrence.get("cid") or layer.cid
            body_steps = getattr(layer, "body_steps", ()) or ()
            rewritten.append(
                NestedManagerStepV1(
                    nested_protocol=nested_protocol,
                    body_steps=body_steps,
                    fragment_cid=occurrence_cid,
                    occurrence_cid=occurrence_cid,
                )
            )
            continue
        rewritten.append(step)
    if layer_idx == 0:
        return frame
    return SimpleNamespace(
        frame_cid=frame.frame_cid,
        generator_steps=tuple(rewritten),
        runtime_entries=tuple(getattr(frame, "runtime_entries", ()) or ()),
        parameters=tuple(getattr(frame, "parameters", ()) or ()),
        definition_site=getattr(frame, "definition_site", None),
    )


def _project_generator_lifecycle_faces(
    generator_target,
) -> tuple[
    tuple[GeneratorEnterHaltFaceV1, ...],
    tuple[GeneratorYieldFaceV1, ...],
    tuple[GeneratorExitHaltFaceV1, ...],
]:
    """Project enter-halt, yield, and post-yield exit-halt faces.

    Walks typed FunctionDef body statements only — never source text scanning
    or decorator/provider spelling. Pre-yield raises → enter-halt; yields →
    yield faces; post-yield raises (and try/finally raises) → exit-halt with
    temporal_phase=post-yield. Faces are never recombined.
    """
    from sugar_source_tree.nodes import FunctionDef, If, Raise, Try

    if not isinstance(generator_target, FunctionDef):
        return (), (), ()
    enter_halts: list[GeneratorEnterHaltFaceV1] = []
    yields: list[GeneratorYieldFaceV1] = []
    exit_halts: list[GeneratorExitHaltFaceV1] = []
    past_yield = False
    for statement in generator_target.body:
        if _is_yield_expression_statement(statement):
            past_yield = True
            yields.append(_mint_yield_face(statement))
            continue
        if isinstance(statement, Try) and statement.finalbody:
            # try: yield ... finally: raise — yield first, then exit-halt.
            for nested in statement.body:
                if _is_yield_expression_statement(nested):
                    past_yield = True
                    yields.append(_mint_yield_face(nested))
            for nested in statement.finalbody:
                if isinstance(nested, Raise) and past_yield:
                    face = _mint_exit_halt_face(nested, guard_source=None)
                    if face is not None:
                        exit_halts.append(face)
            continue
        if not past_yield:
            if isinstance(statement, Raise):
                face = _mint_enter_halt_face(statement, guard_source=None)
                if face is not None:
                    enter_halts.append(face)
                continue
            if isinstance(statement, If):
                enter_halts.extend(_if_raise_enter_halts(statement))
            continue
        # Post-yield.
        if isinstance(statement, Raise):
            face = _mint_exit_halt_face(statement, guard_source=None)
            if face is not None:
                exit_halts.append(face)
            continue
        if isinstance(statement, If):
            exit_halts.extend(_if_raise_exit_halts(statement))
    return tuple(enter_halts), tuple(yields), tuple(exit_halts)


def _if_raise_enter_halts(statement) -> list[GeneratorEnterHaltFaceV1]:
    from sugar_source_tree.nodes import Raise

    faces: list[GeneratorEnterHaltFaceV1] = []
    guard = statement.test.fragment.seal().to_dict()
    for nested in statement.body:
        if isinstance(nested, Raise):
            face = _mint_enter_halt_face(nested, guard_source=guard)
            if face is not None:
                faces.append(face)
    for nested in statement.orelse:
        if isinstance(nested, Raise):
            else_guard = {
                "kind": "generator-branch-else-guard",
                "schemaVersion": "1",
                "ifTest": guard,
                "branch": "orelse",
            }
            face = _mint_enter_halt_face(nested, guard_source=else_guard)
            if face is not None:
                faces.append(face)
    return faces


def _if_raise_exit_halts(statement) -> list[GeneratorExitHaltFaceV1]:
    from sugar_source_tree.nodes import Raise

    faces: list[GeneratorExitHaltFaceV1] = []
    guard = statement.test.fragment.seal().to_dict()
    for nested in statement.body:
        if isinstance(nested, Raise):
            face = _mint_exit_halt_face(nested, guard_source=guard)
            if face is not None:
                faces.append(face)
    for nested in statement.orelse:
        if isinstance(nested, Raise):
            else_guard = {
                "kind": "generator-branch-else-guard",
                "schemaVersion": "1",
                "ifTest": guard,
                "branch": "orelse",
            }
            face = _mint_exit_halt_face(nested, guard_source=else_guard)
            if face is not None:
                faces.append(face)
    return faces


def _is_yield_expression_statement(statement) -> bool:
    from sugar_source_tree.nodes import Expr, Yield

    return isinstance(statement, Expr) and isinstance(statement.value, Yield)


def _mint_enter_halt_face(
    raise_stmt, *, guard_source: dict | None
) -> GeneratorEnterHaltFaceV1 | None:
    """Mint one enter-halt face from a typed Raise node.

    Exception type identity is the sealed source of the raise's exception
    expression — not a spelling of the class name.
    """
    from sugar_source_tree.nodes import Raise

    if not isinstance(raise_stmt, Raise):
        return None
    exc = getattr(raise_stmt, "exc", None)
    if exc is None:
        return None
    occurrence = raise_stmt.fragment.seal().to_dict()
    exception_type_source = exc.fragment.seal().to_dict()
    return GeneratorEnterHaltFaceV1.mint(
        occurrence=occurrence,
        exception_type_source=exception_type_source,
        guard_source=guard_source,
    )


def _mint_exit_halt_face(
    raise_stmt, *, guard_source: dict | None
) -> GeneratorExitHaltFaceV1 | None:
    """Mint one post-yield exit-halt face from a typed Raise node."""
    from sugar_source_tree.nodes import Raise

    if not isinstance(raise_stmt, Raise):
        return None
    exc = getattr(raise_stmt, "exc", None)
    if exc is None:
        return None
    return GeneratorExitHaltFaceV1.mint(
        occurrence=raise_stmt.fragment.seal().to_dict(),
        exception_type_source=exc.fragment.seal().to_dict(),
        guard_source=guard_source,
    )


def _mint_yield_face(statement) -> GeneratorYieldFaceV1:
    from sugar_source_tree.nodes import Expr, Yield

    assert isinstance(statement, Expr) and isinstance(statement.value, Yield)
    yield_node = statement.value
    occurrence = yield_node.fragment.seal().to_dict()
    resource = yield_node.value
    resource_source = None if resource is None else resource.fragment.seal().to_dict()
    return GeneratorYieldFaceV1.mint(
        occurrence=occurrence, resource_source=resource_source
    )


def _protocol_coords_from_generator_decorators(
    generator_target,
    *,
    session,
    graph=None,
    dependency_graphs=None,
    distribution_index=None,
):
    """Construct enter/exit definition sites from generator decorator testimony."""
    from sugar_source_tree.nodes import FunctionDef

    if not isinstance(generator_target, FunctionDef):
        return None
    decorators = getattr(generator_target, "decorators", ()) or ()
    if not decorators:
        return None
    published = []
    for decorator in decorators:
        decorator_fn = _construct_decorator_function(
            decorator,
            session=session,
            graph=graph,
            dependency_graphs=dependency_graphs,
            distribution_index=distribution_index,
        )
        if decorator_fn is None:
            continue
        returned_class = _sole_returned_manager_class(decorator_fn)
        if returned_class is None:
            continue
        coords = _enter_exit_sites_from_class_def(returned_class)
        if coords is None:
            continue
        published.append(coords)
    # Exactly one decorator arm may yield protocol coordinates; several would
    # reintroduce first-candidate selection across independent wrappers.
    if len(published) != 1:
        return None
    return published[0]


def _construct_decorator_function(
    decorator,
    *,
    session,
    graph=None,
    dependency_graphs=None,
    distribution_index=None,
):
    """Resolve and construct the decorator callable from typed import testimony."""
    from sugar_source_tree.nodes import FunctionDef, Name

    from .dependency_artifact import (
        DependencyArtifactAuthenticationError,
        ResolvedPythonObjectV1,
        authenticate_dependency_top_level,
        resolve_authenticated_module_export,
    )
    from .manager_construction import (
        ManagerConstructionGapV1,
        resolve_source_visible_frame,
    )

    binding = _decorator_module_export_binding(decorator)
    if binding is None:
        # Same-module FunctionDef bound under the decorator Name.
        if isinstance(decorator, Name):
            binds = (decorator.unit.module_direct_bindings or {}).get(decorator.id, ())
            if len(binds) == 1 and isinstance(binds[0], FunctionDef):
                return binds[0]
        return None
    module_name, exported_name = binding
    graphs = []
    if graph is not None:
        graphs.append(graph)
    top_level = module_name.split(".", 1)[0]
    local_graphs = dependency_graphs if dependency_graphs is not None else {}
    authenticated_dependency = local_graphs.get(top_level)
    if authenticated_dependency is None and session is not None and session.enabled:
        authenticated_dependency = session.dependency_graphs.get(top_level)
        if authenticated_dependency is not None:
            local_graphs[top_level] = authenticated_dependency
            if dependency_graphs is not None:
                dependency_graphs[top_level] = authenticated_dependency
    if authenticated_dependency is None:
        try:
            authenticated_dependency = authenticate_dependency_top_level(
                top_level, distribution_index=distribution_index
            )
        except DependencyArtifactAuthenticationError:
            authenticated_dependency = None
        else:
            local_graphs[top_level] = authenticated_dependency
            if dependency_graphs is not None:
                dependency_graphs[top_level] = authenticated_dependency
            if session is not None and session.enabled:
                session.dependency_graphs[top_level] = authenticated_dependency
    if authenticated_dependency is not None and authenticated_dependency not in graphs:
        graphs.append(authenticated_dependency)
    if not any(module_name in candidate.modules for candidate in graphs):
        try:
            authenticated_dependency = authenticate_dependency_top_level(
                top_level, distribution_index=distribution_index
            )
        except DependencyArtifactAuthenticationError:
            return None
        if session is not None and session.enabled:
            session.dependency_graphs[top_level] = authenticated_dependency
        if dependency_graphs is not None:
            dependency_graphs[top_level] = authenticated_dependency
        if authenticated_dependency not in graphs:
            graphs.append(authenticated_dependency)
    resolved = None
    resolved_graph = None
    for candidate in graphs:
        if module_name not in candidate.modules:
            continue
        result = resolve_authenticated_module_export(
            graph=candidate,
            binding_cid=decorator.fragment.seal().cid,
            module_name=module_name,
            exported_name=exported_name,
            session=session,
        )
        if isinstance(result, ResolvedPythonObjectV1):
            resolved = result
            resolved_graph = candidate
            break
    if resolved is None or resolved_graph is None:
        return None
    frame_result = resolve_source_visible_frame(
        resolved,
        graph=resolved_graph,
        dependency_graphs=dependency_graphs,
        session=session,
    )
    if isinstance(frame_result, ManagerConstructionGapV1):
        return None
    _frame, target = frame_result
    if not isinstance(target, FunctionDef):
        return None
    return target


def _decorator_module_export_binding(decorator) -> tuple[str, str] | None:
    """Read (module_name, exported_name) from authenticated import bindings."""
    from sugar_source_tree.nodes import Attribute, Import, ImportFrom, Name

    unit = decorator.unit
    bindings = unit.module_direct_bindings or {}
    if isinstance(decorator, Name):
        binds = bindings.get(decorator.id, ())
        if len(binds) != 1:
            return None
        bind = binds[0]
        if not isinstance(bind, ImportFrom) or not bind.module:
            return None
        for alias in bind.names:
            local = alias.asname or alias.name
            if local == decorator.id:
                return bind.module, alias.name
        return None
    if isinstance(decorator, Attribute) and isinstance(decorator.value, Name):
        binds = bindings.get(decorator.value.id, ())
        if len(binds) != 1:
            return None
        bind = binds[0]
        if isinstance(bind, Import):
            for alias in bind.names:
                local = alias.asname or alias.name
                if local == decorator.value.id:
                    return alias.name, decorator.attr
        if isinstance(bind, ImportFrom) and bind.module:
            # ``from pkg import mod`` then ``@mod.decorator`` — module is
            # pkg.mod when the imported name is a module re-export.
            for alias in bind.names:
                local = alias.asname or alias.name
                if local == decorator.value.id:
                    return f"{bind.module}.{alias.name}", decorator.attr
        return None
    return None


def _sole_returned_manager_class(decorator_fn):
    """Project the sole class the decorator's returned helper constructs.

    The decorator body must return exactly one nested FunctionDef (the helper).
    That helper must construct exactly one class on return. Multiple helpers or
    multiple classes refuse — never first-candidate selection.
    """
    from sugar_source_tree.nodes import ClassDef, FunctionDef, Name, Return

    nested = {
        stmt.name: stmt for stmt in decorator_fn.body if isinstance(stmt, FunctionDef)
    }
    returned_helpers = []
    for stmt in decorator_fn.body:
        if not isinstance(stmt, Return):
            continue
        value = stmt.value
        if isinstance(value, Name) and value.id in nested:
            returned_helpers.append(nested[value.id])
    if len(returned_helpers) != 1:
        # Direct ``return Class(...)`` without a nested helper is also sole.
        direct = _classes_constructed_by_returns(decorator_fn.body)
        if len(direct) == 1:
            return direct[0]
        return None
    classes = _classes_constructed_by_returns(returned_helpers[0].body)
    if len(classes) != 1:
        return None
    return classes[0]


def _classes_constructed_by_returns(statements) -> tuple:
    """ClassDefs reached by ``return Name(...)`` through module bindings.

    Walks typed statement structure (If/For/With/Try bodies) so branched
    helpers that construct two classes refuse sole-class projection. This is
    child-node projection, not source scanning.
    """
    from sugar_source_tree.nodes import (
        Call,
        ClassDef,
        For,
        If,
        Name,
        Return,
        Try,
        While,
        With,
    )

    found = []
    seen = set()

    def visit(stmts) -> None:
        for stmt in stmts:
            if isinstance(stmt, Return):
                value = stmt.value
                if not isinstance(value, Call) or not isinstance(value.func, Name):
                    continue
                binds = (value.func.unit.module_direct_bindings or {}).get(
                    value.func.id, ()
                )
                for bind in binds:
                    if not isinstance(bind, ClassDef):
                        continue
                    key = (
                        bind.unit.source_cid,
                        bind.line_col_span().start_line,
                        bind.line_col_span().start_col,
                        bind.line_col_span().end_line,
                        bind.line_col_span().end_col,
                    )
                    if key in seen:
                        continue
                    seen.add(key)
                    found.append(bind)
            elif isinstance(stmt, If):
                visit(stmt.body)
                visit(stmt.orelse)
            elif isinstance(stmt, (For, While)):
                visit(stmt.body)
                visit(stmt.orelse)
            elif isinstance(stmt, With):
                visit(stmt.body)
            elif isinstance(stmt, Try):
                visit(stmt.body)
                for handler in stmt.handlers:
                    visit(handler.body)
                visit(stmt.orelse)
                visit(stmt.finalbody)

    visit(statements)
    return tuple(found)


def _enter_exit_sites_from_class_def(class_def):
    """Read constructed ``__enter__`` / ``__exit__`` definition sites."""
    from sugar_source_tree.nodes import FunctionDef

    enter = exit_ = None
    for item in class_def.body:
        if not isinstance(item, FunctionDef):
            continue
        frame = item.source_visible_call_frame()
        site = frame.definition_site
        if item.name == "__enter__":
            enter = site
        elif item.name == "__exit__":
            exit_ = site
    if enter is None or exit_ is None or enter == exit_:
        return None
    return enter, exit_


def _projected_manager_call_uses(source_file):
    """Project ordinary reaching assignments into context-manager call uses.

    ``WithItem.substitute`` retains the consumer's immutable use coordinate
    while the existing block substitution transaction replaces a bare Name
    with its reaching value.  Reading that projection preserves shadowing and
    undecided values without creating a second binding mechanism here.
    """
    from sugar_lift_py_tests.context_manager_resolution import (
        SourceFragmentCoordinateV1,
    )
    from sugar_source_tree.nodes import AsyncWith, Call, With

    manager_scope_types = (With, AsyncWith)

    uses = {}

    def collect(root, *, projected_names: bool) -> None:
        for node in root.walk():
            if not isinstance(node, manager_scope_types):
                continue
            for item in node.items:
                expr = item.context_expr
                if not isinstance(expr, Call):
                    continue
                if not projected_names and hasattr(item, "manager_use_site_start_line"):
                    continue
                span = expr.line_col_span()
                start_line, start_col, end_line, end_col = item._manager_use_site_span()
                if projected_names and (
                    start_line,
                    start_col,
                    end_line,
                    end_col,
                ) == (
                    span.start_line,
                    span.start_col,
                    span.end_line,
                    span.end_col,
                ):
                    # The projected frame also contains ordinary direct-call
                    # managers.  Their existing source node is authoritative;
                    # only a call borrowed from another locus is an assigned
                    # manager projection.
                    continue
                coordinate = SourceFragmentCoordinateV1(
                    expr.unit.source_cid,
                    start_line,
                    start_col,
                    end_line,
                    end_col,
                )
                uses[(span.start_line, span.start_col, span.end_line, span.end_col)] = (
                    coordinate,
                    expr,
                    item._exit_face_id(),
                )

    # Preserve the original direct-call route exactly.
    collect(source_file.root, projected_names=False)

    # Project frames that contain a bare-Name manager — single-item
    # ``with m:`` and multi-item ``with m, n:`` alike.  The multi-item
    # shape was the first enrolled reproducer (#6489); a returned resource
    # assigned once and consumed as a single Name is the same projection,
    # not a second binding mechanism.  Module-wide substitution is still
    # avoided: only functions that actually write a bare-Name manager are
    # projected, so unrelated frames do not demand contracts.
    for function in source_file.functions():
        if not any(
            isinstance(node, With)
            and any(item.context_expr.kind == "Name" for item in node.items)
            for node in function.walk()
        ):
            continue
        collect(function.substitute({}), projected_names=True)

    return uses


def _populate_body_defect_kind_detail(exc: BaseException) -> tuple[str, str]:
    """Name a populate-path body defect for cite-and-continue.

    SugarNotWritten → ``source-body-gap`` (existing #7063 arm).
    TypeError → ``source-body-type-error`` (#7062 second costume: construction
    require_* / IfExpSugar post_init failure that used to abort the open and
    bank functionsTotal=0).

    Callers must catch only these named classes — never bare ``except``.
    """
    from sugar_source_tree.panic import SugarNotWritten

    if isinstance(exc, SugarNotWritten):
        observed = getattr(exc, "observed", None) or str(exc)
        return "source-body-gap", str(observed)
    if isinstance(exc, TypeError):
        return "source-body-type-error", f"TypeError: {exc}"
    raise TypeError(
        f"_populate_body_defect_kind_detail got unexpected {type(exc).__name__}; "
        f"callers must catch only SugarNotWritten and TypeError"
    ) from exc


def _gap_kind_and_detail(gap) -> tuple[str, str | None]:
    """Read a producer's ALREADY-SEPARATE kind and detail, unfused.

    Every producer that reaches here declares ``kind`` as a closed ``Literal``
    with ``detail`` as its own field.  This function used to be
    ``_construction_gap_kind``, which returned ``f"{kind}:{detail}"`` and
    truncated the result to 80 chars -- a key that can be truncated is not an
    identity, and the fused strings it minted are what put a callee spelling at
    79% of the pinned-pandas resolution board.  The structure was never
    missing; the reporting layer was throwing it away and rebuilding a worse
    one from a string.
    """
    kind = getattr(gap, "kind", None) or "no-derived-contract"
    detail = getattr(gap, "detail", None)
    return str(kind), (str(detail) if detail else None)


def _install_derivation_gap(
    context, coordinate, receipt, kind: str, detail: str | None = None
) -> None:
    """Publish a CM resolution gap for this enrolled demand.

    Derivation ran; the demand has no ``ContextManagerContractRefV1``.
    Install the row and continue — do not call deleted C3 ground mint
    (``enrolled_demand_unresolved_ground``). With consumption panics on the
    gap via ``ContextManagerResolutionConstructionGap`` (L3d require door).
    """
    from sugar_lift_py_tests.context_manager_resolution import (
        ContextManagerResolutionGapV1,
    )

    gap = ContextManagerResolutionGapV1(
        receipt.demand.get("cid", receipt.use["cid"]),
        coordinate,
        receipt.target_symbol,
        kind,
        (),
        detail,
    )
    context.source_derived_contract_refs[coordinate] = gap
