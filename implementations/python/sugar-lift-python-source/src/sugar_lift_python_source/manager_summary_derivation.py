"""Project constructed source-manager testimony into the closed CM schema."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
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
    SourceConstructorFacesCompletionV1,
    SourceEnterFacesCompletionV1,
    SourceExitFacesCompletionV1,
    SuppressesModeV1,
    TotalCompletionV1,
    VariadicKeywordEntryProjectionV1,
    VariadicKeywordV1,
    VariadicPositionalV1,
    semantics_to_value,
)
from sugar_lift_py_tests.floor import BlockValue, ReturnValue, TermValue
from sugar_lift_py_tests.floor.branch_result_coordinate import (
    resolve_branch_result_guards as _resolve_branch_result_guards,
)
from sugar_lift_py_tests.ir import PrimitiveSort
from sugar_lift_py_tests.outcome import Complete, Completed, Halted, outcome_to_exitset

from .canonical import cid_of_json
from .manager_protocol_construction import (
    ConstructedManagerProtocolV1,
    GeneratorBackedManagerProtocolV1,
    ManagerProtocolConstructionGapV1,
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
    Exception-type operands likewise authenticate only operand identity: they
    cannot replace an unconstructed enter or exit with Expects-Raise testimony.
    """
    from sugar_lift_py_tests.gap.panic import ConstructionPanic
    from sugar_lift_py_tests.outcome import ExitSet

    from sugar_lift_py_tests.source_call_frame import SourceCallBindingGap
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
    except (OpaqueSourceCallResolutionGap, SugarNotWritten, SourceCallBindingGap) as exc:
        owner = getattr(exc, "owner", None) or type(exc).__name__
        observed = getattr(exc, "observed", None) or str(exc)
        return DerivedManagerSummaryGapV1(
            "enter-may-halt",
            protocol.protocol_construction_cid,
            f"{owner}:{observed}",
        )
    enter_completion = TotalCompletionV1()
    enter_halted = tuple(face for face in enter.exits if not isinstance(face, Completed))
    if (
        not enter.exits
        or not any(isinstance(face, Completed) for face in enter.exits)
        or (
            enter_halted
            and (
                not isinstance(protocol, ConstructedManagerProtocolV1)
                or any(
                    not isinstance(face, Halted) or face.effect is None
                    for face in enter_halted
                )
            )
        )
    ):
        return DerivedManagerSummaryGapV1(
            "enter-may-halt", protocol.protocol_construction_cid, "__enter__ ExitSet"
        )
    if enter_halted:
        # An enter that may halt is not a total resource. It is admitted only
        # for the real source protocol: With runs this same enter frame, and
        # each enter halt leaves the With as its own effect before body/exit.
        enter_completion = SourceEnterFacesCompletionV1()
    # An effect-boundary theorem has no enter-completion field, so it cannot
    # carry enter halts; only the protocol-resource arm below may. It may
    # carry construction halts: those leave the With before anything is
    # entered, so the boundary is sealed over completed construction alone.
    construction_halts = _construction_halts(protocol)
    boundary_door = (
        behavior is not None and not enter_halted and construction_halts is not None
    )
    if boundary_door:
        factored = _derive_factored_effect_boundary(protocol, behavior)
        if factored is not None:
            return factored
    try:
        exit_outcome = protocol.exit_outcome()
        from sugar_lift_py_tests.caller_parameter_contract import (
            NativeOperationExitCarrierV1,
        )
        from sugar_lift_py_tests.floor.manager_coordinate import ExitValueCoordinate

        # A deferred lookup is not a suppression theorem. Admit only the real
        # source protocol, whose exit will run with each actual With body face.
        # Other construction refusals still take the typed gap doors below.
        if (
            isinstance(protocol, ConstructedManagerProtocolV1)
            and isinstance(exit_outcome, NativeOperationExitCarrierV1)
            and any(coordinate is not None for coordinate in exit_outcome.coordinates)
            and all(
                coordinate is None
                or (
                    isinstance(coordinate, ExitValueCoordinate)
                    and coordinate.face_id == protocol.exit_face_id
                )
                for coordinate in exit_outcome.coordinates
            )
        ):
            if boundary_door:
                boundary = _derive_effect_boundary_from_deferred_carrier(
                    exit_outcome, protocol, behavior
                )
                if boundary is not None:
                    boundary = _with_construction_faces(boundary, construction_halts)
                    signature = _signature_for_behavior(behavior, boundary)
                    return _sealed_summary(protocol, boundary, signature)
            semantics = ProtocolResourceSemanticsV1(
                EnterResultContractV1(PrimitiveSort("Value")),
                ExitContractV1(ReturnTruthinessDispositionV1()),
            )
            return _sealed_summary(
                protocol, semantics, _signature_for_behavior(behavior, semantics)
            )
        exit_ = outcome_to_exitset(exit_outcome)
    except ConstructionPanic as panic:
        owner = getattr(getattr(panic, "info", None), "owner", None) or "exit"
        observed = getattr(getattr(panic, "info", None), "observed", None) or str(panic)
        return DerivedManagerSummaryGapV1(
            "exit-may-halt",
            protocol.protocol_construction_cid,
            f"{owner}:{observed}",
        )
    except (OpaqueSourceCallResolutionGap, SugarNotWritten, SourceCallBindingGap) as exc:
        owner = getattr(exc, "owner", None) or type(exc).__name__
        observed = getattr(exc, "observed", None) or str(exc)
        return DerivedManagerSummaryGapV1(
            "exit-may-halt",
            protocol.protocol_construction_cid,
            f"{owner}:{observed}",
        )
    boundary = (
        _derive_effect_boundary(exit_, protocol, behavior) if boundary_door else None
    )
    if boundary is not None:
        boundary = _with_construction_faces(boundary, construction_halts)
        signature = _signature_for_behavior(behavior, boundary)
        return _sealed_summary(protocol, boundary, signature)
    # A type operand is data, not evidence that this callee consumes it.
    # Only the native exit theorem above can authenticate an effect boundary;
    # unresolved/non-total protocol construction must remain a typed gap.
    if not exit_.exits:
        return DerivedManagerSummaryGapV1(
            "exit-may-halt", protocol.protocol_construction_cid, "__exit__ ExitSet"
        )
    completed = tuple(face for face in exit_.exits if isinstance(face, Completed))
    halted = tuple(face for face in exit_.exits if not isinstance(face, Completed))
    completion = TotalCompletionV1()
    if halted:
        # An exit that may raise is not a total resource. It is admitted only
        # for the real source protocol: With re-runs this same exit frame per
        # body face, and every exit halt supersedes that body exit as its own
        # typed effect. A face without a typed effect stays the gap.
        if not isinstance(protocol, ConstructedManagerProtocolV1) or any(
            not isinstance(face, Halted) or face.effect is None for face in halted
        ):
            return DerivedManagerSummaryGapV1(
                "exit-may-halt", protocol.protocol_construction_cid, "__exit__ ExitSet"
            )
        completion = SourceExitFacesCompletionV1()
    disposition = (
        NeverSuppressesDispositionV1()
        if all(_exact_never_suppresses(face.value) for face in completed)
        else ReturnTruthinessDispositionV1()
    )
    semantics = ProtocolResourceSemanticsV1(
        EnterResultContractV1(PrimitiveSort("Value"), enter_completion),
        ExitContractV1(disposition, completion),
    )
    signature = _signature_for_behavior(behavior, semantics)
    return _sealed_summary(protocol, semantics, signature)


def _construction_halts(protocol):
    """Typed halts of the manager's own construction; ``None`` if any is untyped.

    Construction is the With's context expression: it runs before anything
    is entered. Each typed halt leaves the With as itself, so a boundary may
    be sealed over the completed construction faces alone. An untyped halt
    cannot leave as itself and closes the boundary door.
    """
    from sugar_lift_py_tests.floor import ReceiverStatePartitionValue

    state = getattr(protocol, "receiver_state", None)
    if not isinstance(state, ReceiverStatePartitionValue):
        return ()
    faces = state.constructor_faces()
    return None if faces is None else faces[0]


def _with_construction_faces(boundary, construction_halts):
    if not construction_halts:
        return boundary
    return replace(boundary, construction=SourceConstructorFacesCompletionV1())


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
        expected_index = _formal_index_for_matches_expected(
            formula, behavior, actual_terms
        )
    if expected_index is None:
        return None
    message_index = _formal_index_for_coordinate(
        formula, actual_terms, "python:exit_value"
    )
    if message_index is None:
        message_index = _formal_index_for_matches_message(
            formula, behavior, actual_terms
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
    match_failed_halts = tuple(
        face
        for face in halted
        if _halt_complements_true_return(face, exit_set)
        or _halt_negates_matches_conjunct_of_true_return(face, exit_set)
    )
    if any(
        face not in absent_effect_halts and face not in match_failed_halts
        for face in halted
    ):
        # A source-visible exit failure is not evidence that matching effects
        # are consumed.  It remains a protocol-construction gap until its own
        # outgoing face is represented by the summary schema.  The complement
        # of a completed ``return True`` face is that same partition's
        # match-failed halt, not a foreign failure.
        return None
    if not absent_effect_halts and _completed_faces_have_bodyless_free_calls(
        exit_set
    ):
        # A bodyless free-function call on a completed face (pytest's
        # ``fail("DID NOT RAISE ...")`` today) is unresolved halt testimony.
        # Sealing SuppressesMode here would invent that the manager does not
        # require an exception.
        return None
    from sugar_lift_py_tests.floor.none_value import NoneValue

    if message_index is not None:
        message_pattern = OptionalFormalArgumentProjectionV1(message_index)
    else:
        message_pattern = _keyword_entry_cited_by_field(behavior, "match")
    match_field = _receiver_field_value(behavior, "match")
    if (
        message_pattern is None
        and match_field is not None
        and not isinstance(match_field, NoneValue)
    ):
        # A stored non-None match that is not a unique factory formal or
        # **kwargs entry is an unprojected pattern, not NoMessagePattern.
        # Seeded match=None still projects as an omitted message.
        return None
    if message_pattern is None:
        supplied = _keyword_supplied_value(behavior, "match")
        if supplied is not None and not isinstance(supplied, NoneValue):
            # Factory **kwargs carried a pattern that was not cited. A
            # stored None after a wiped compile is not match=None.
            return None
    expects = bool(absent_effect_halts)
    return EffectBoundarySemanticsV1(
        ExpectsModeV1() if expects else SuppressesModeV1(),
        RaiseEffectKindV1(),
        FormalArgumentProjectionV1(expected_index),
        NoMessagePatternV1() if message_pattern is None else message_pattern,
        ExceptionInfoBindingV1(),
    )


def _derive_effect_boundary_from_deferred_carrier(
    carrier, protocol, behavior, receiver=None
):
    """Derive an effect boundary from a short-circuited deferred message lookup.

    The identity half is already a completed ``PredicateValue`` — identity is
    total. The continuing half is a deferred ``effect.message`` lookup that
    then compares by native ``==``. That comparison is not rewritten into a
    total ``eq`` formula (payload ``__eq__`` can raise). The message formal is
    the unique factory actual stored in the receiver field named by the
    comparison's other operand.

    A source may wrap the comparison as ``field is None or effect.message ==
    field``. That inner ``or`` is not itself an EffectBoundary; it only records
    that this face already decided the pattern is present. The outer ``and``
    remains the identity half. ``==`` still is not treated as a total formula.
    """
    from sugar_lift_py_tests.floor.manager_coordinate import ExitValueCoordinate
    from sugar_lift_py_tests.floor.predicate_value import PredicateValue
    from sugar_lift_py_tests.floor.string_value import StringValue
    from sugar_lift_py_tests.outcome import Completed, Halted
    from sugar_lift_py_tests.sugar.equality_op_sugar import EqualityOpSugar

    if (
        carrier.demand.operator != "attribute_named"
        or len(carrier.operands) < 2
        or not isinstance(carrier.operands[1], StringValue)
        or carrier.operands[1].value != "message"
        or not carrier.coordinates
        or not isinstance(carrier.coordinates[0], ExitValueCoordinate)
        or carrier.coordinates[0].face_id != protocol.exit_face_id
        or not carrier.short_circuits
        or len(carrier.short_circuits) > 2
    ):
        return None

    continuing_guard, stopped, _continuing_face, _stopped_face = (
        carrier.short_circuits[-1]
    )
    if (
        len(stopped.exits) != 1
        or not isinstance(stopped.exits[0], Completed)
        or not isinstance(stopped.exits[0].value, PredicateValue)
        or stopped.exits[0].value.formula != continuing_guard
    ):
        # And returns the identity predicate on the stopping face. Or returns
        # that predicate under the complementary guard, which is a different
        # theorem than EffectBoundary's type-and-message conjunction.
        return None

    actuals = tuple(behavior.formal_actual_values)
    actual_terms = tuple(
        value.to_term(owner=behavior.resolved_object_cid) for value in actuals
    )
    expected_index = _formal_index_for_coordinate(
        continuing_guard, actual_terms, "python:exit_type"
    )
    if expected_index is None:
        return None

    equalities = [
        item
        for item in _closed_over_continuation_values(carrier)
        if isinstance(item, EqualityOpSugar)
    ]
    if len(equalities) != 1:
        return None
    message_index = _message_pattern_formal_index(
        equalities[0], behavior, actual_terms, receiver=receiver
    )
    if message_index == expected_index:
        return None
    if message_index is not None:
        message_pattern = OptionalFormalArgumentProjectionV1(message_index)
    else:
        field_name = _message_comparison_receiver_field(equalities[0])
        message_pattern = (
            _keyword_entry_cited_by_field(
                behavior, field_name, receiver=receiver
            )
            if field_name
            else None
        )
        if message_pattern is None:
            return None
    if len(carrier.short_circuits) == 2:
        field_name = _message_comparison_receiver_field(equalities[0])
        field_value = _receiver_field_value(behavior, field_name, receiver=receiver)
        if not _inner_short_circuit_is_absent_pattern(
            carrier.short_circuits[0][1], field_value
        ):
            return None

    from sugar_lift_py_tests.floor import BranchResultAuthentication

    authentications = [
        item
        for obj in _closed_over_continuation_values(carrier)
        for item in getattr(obj, "entries", ())
        if isinstance(item, BranchResultAuthentication)
    ]
    halted = ()
    if carrier.prefix_composition is not None:
        resolved = carrier.prefix_composition[0]
        halted = tuple(face for face in resolved if isinstance(face, Halted))
    absent_effect_halts = tuple(
        face
        for face in halted
        if any(
            _authentication_is_no_effect(item, protocol.exit_face_id)
            and _formula_mentions_branch_slot(face.guard, item.slot.slot_id)
            for item in authentications
        )
    )
    if any(face not in absent_effect_halts for face in halted):
        return None

    return EffectBoundarySemanticsV1(
        ExpectsModeV1() if absent_effect_halts else SuppressesModeV1(),
        RaiseEffectKindV1(),
        FormalArgumentProjectionV1(expected_index),
        message_pattern,
        ExceptionInfoBindingV1(),
    )


def _closed_over_continuation_values(carrier):
    """The constructed objects a deferred carrier's continuations still hold."""
    values = []
    for step in carrier.continuations:
        closure = getattr(step, "__closure__", None)
        if not closure:
            continue
        values.extend(cell.cell_contents for cell in closure)
    return values


def _message_comparison_receiver_field(equality):
    from sugar_lift_py_tests.sugar.attribute_sugar import AttributeSugar

    sides = (equality.left, equality.right)
    message_sides = [
        side
        for side in sides
        if isinstance(side, AttributeSugar) and side.name == "message"
    ]
    other_sides = [side for side in sides if side not in message_sides]
    if len(message_sides) != 1 or len(other_sides) != 1:
        return None
    return _receiver_attribute_name(other_sides[0])


def _message_pattern_formal_index(equality, behavior, actual_terms, receiver=None):
    field_name = _message_comparison_receiver_field(equality)
    if field_name is None:
        return None
    value = _receiver_field_value(behavior, field_name, receiver=receiver)
    if value is None:
        return None
    to_term = getattr(value, "to_term", None)
    if not callable(to_term):
        return None
    term = to_term(owner=behavior.resolved_object_cid)
    matches = [index for index, actual in enumerate(actual_terms) if actual == term]
    return matches[0] if len(matches) == 1 else None


def _receiver_attribute_name(sugar):
    from sugar_lift_py_tests.sugar.attribute_sugar import AttributeSugar
    from sugar_lift_py_tests.sugar.binding_coordinate_ref_sugar import (
        BindingCoordinateRefSugar,
    )

    if not isinstance(sugar, AttributeSugar):
        return None
    receiver = sugar.receiver
    if not isinstance(receiver, BindingCoordinateRefSugar):
        return None
    if getattr(receiver.coordinate, "projection_path", None) != ("formal", 0):
        return None
    return sugar.name


def _unconditional_partition_leaf(state):
    """A one-face true-guard partition is already the constructed receiver.

    Field lookup must not invent a unique field from a multi-face or
    symbolically-guarded partition: those leaves are still branch-local.
    """
    from sugar_lift_py_tests.floor import ObjectValue, ReceiverStatePartitionValue
    from sugar_lift_py_tests.outcome.exit_set import true_guard

    from .manager_protocol_construction import _completed_receiver_exits

    if not isinstance(state, ReceiverStatePartitionValue):
        return None
    completed = [
        face
        for face in _completed_receiver_exits(state).exits
        if isinstance(face, Completed) and isinstance(face.value, ObjectValue)
    ]
    if len(completed) != 1:
        return None
    if completed[0].guard != true_guard():
        # The one completed receiver is unconditional where the manager
        # exists when every other construction face is a typed halt: those
        # leave the With before anything reads a field.
        faces = state.constructor_faces()
        if faces is None or not faces[0]:
            return None
    return completed[0].value


def _receiver_field_value(behavior, name, receiver=None):
    state = behavior.receiver_state if receiver is None else receiver
    fields = getattr(state, "fields", ())
    if not fields:
        leaf = _unconditional_partition_leaf(state)
        fields = getattr(leaf, "fields", ()) if leaf is not None else ()
    matches = [
        field.value for field in fields if getattr(field, "name", None) == name
    ]
    return matches[0] if len(matches) == 1 else None


def _inner_short_circuit_is_absent_pattern(stopped, field_value):
    """True when the inner ``or`` stopped because ``field is None`` is false.

    A constructed string is disjoint from ``None``, so ``"needle" is None``
    folds to exact ``False``. A symbolic field emits an ``identity`` formula
    against ``None``. Other inner guards are not the optional-pattern theorem.
    """
    from sugar_lift_py_tests.floor.none_value import NoneValue
    from sugar_lift_py_tests.floor.predicate_value import PredicateValue
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
        FalseBoolLiteralSugar,
    )

    if field_value is None:
        return False
    if len(stopped.exits) != 1 or not isinstance(stopped.exits[0], Completed):
        return False
    value = stopped.exits[0].value
    if isinstance(value, FalseBoolLiteralSugar):
        return type(field_value) is not NoneValue
    if not isinstance(value, PredicateValue):
        return False
    formula = value.formula
    if getattr(formula, "name", None) != "identity":
        return False
    operands = getattr(formula, "operands", ())
    if len(operands) != 2:
        return False
    return NoneValue().to_term(owner="") in operands


def _derive_boundary_for_receiver(protocol, behavior, receiver):
    """Derive one EffectBoundary from a single completed constructor face."""
    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )
    from sugar_lift_py_tests.floor.manager_coordinate import ExitValueCoordinate
    from sugar_lift_py_tests.gap.panic import ConstructionPanic
    from sugar_lift_py_tests.source_call_frame import SourceCallBindingGap
    from sugar_source_tree.panic import OpaqueSourceCallResolutionGap, SugarNotWritten

    specialized = replace(protocol, receiver_state=receiver)
    try:
        exit_outcome = specialized.exit_outcome()
    except (ConstructionPanic, OpaqueSourceCallResolutionGap, SugarNotWritten, SourceCallBindingGap):
        return None
    if (
        isinstance(exit_outcome, NativeOperationExitCarrierV1)
        and any(coordinate is not None for coordinate in exit_outcome.coordinates)
        and all(
            coordinate is None
            or (
                isinstance(coordinate, ExitValueCoordinate)
                and coordinate.face_id == protocol.exit_face_id
            )
            for coordinate in exit_outcome.coordinates
        )
    ):
        return _derive_effect_boundary_from_deferred_carrier(
            exit_outcome, specialized, behavior, receiver=receiver
        )
    try:
        exit_ = outcome_to_exitset(exit_outcome)
    except (ConstructionPanic, OpaqueSourceCallResolutionGap, SugarNotWritten, SourceCallBindingGap):
        return None
    return _derive_effect_boundary(exit_, specialized, behavior)


def _derive_factored_effect_boundary(protocol, behavior):
    """Keep constructor-partitioned match faces as guarded alternatives.

    ``match=None`` and ``match=pattern`` are different receiver states, not one
    sealed optional operand. Each completed leaf keeps the EffectBoundary that
    its own fields justify; the faces are never recombined into one summary CID.
    """
    from sugar_lift_py_tests.floor import ObjectValue, ReceiverStatePartitionValue
    from sugar_lift_py_tests.outcome import ExitSet

    from .manager_protocol_construction import _completed_receiver_exits

    if not isinstance(behavior.receiver_state, ReceiverStatePartitionValue):
        return None
    completed = [
        face
        for face in _completed_receiver_exits(behavior.receiver_state).exits
        if isinstance(face, Completed) and isinstance(face.value, ObjectValue)
    ]
    if len(completed) < 2:
        return None
    derived = []
    for face in completed:
        boundary = _derive_boundary_for_receiver(protocol, behavior, face.value)
        if not isinstance(boundary, EffectBoundarySemanticsV1):
            return None
        derived.append(Completed(face.guard, boundary))
    none_faces = [
        face
        for face in derived
        if isinstance(face.value.message_pattern_operand, NoMessagePatternV1)
    ]
    pattern_faces = [
        face
        for face in derived
        if isinstance(
            face.value.message_pattern_operand, OptionalFormalArgumentProjectionV1
        )
    ]
    if not none_faces or not pattern_faces:
        return None
    if len(none_faces) + len(pattern_faces) != len(derived):
        return None
    first = derived[0].value
    if any(
        face.value.mode != first.mode
        or face.value.effect_kind != first.effect_kind
        or face.value.expected_type_operand != first.expected_type_operand
        or face.value.binding != first.binding
        for face in derived[1:]
    ):
        return None
    pattern_semantics = pattern_faces[0].value
    halts = _construction_halts(protocol)
    if halts is None:
        return None
    # Construction halts ride beside the guarded boundary faces: each leaves
    # the With as itself before any boundary is entered.
    return FactoredEffectBoundarySummaryV1(
        protocol.protocol_construction_cid,
        protocol.enter_frame_cid,
        protocol.exit_frame_cid,
        ExitSet((*derived, *halts)),
        _signature_for_behavior(behavior, pattern_semantics),
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


def _peel_double_negation(formula):
    from sugar_lift_py_tests.ir import _Connective

    while (
        isinstance(formula, _Connective)
        and formula.kind == "not"
        and len(formula.operands) == 1
    ):
        inner = formula.operands[0]
        if (
            isinstance(inner, _Connective)
            and inner.kind == "not"
            and len(inner.operands) == 1
        ):
            formula = inner.operands[0]
            continue
        break
    return formula


def _direct_matches_call_of_exit_value(formula):
    """``py.truthy(call:*.matches(..., python:exit_value))`` after even nots."""
    from sugar_lift_py_tests.ir import _Atomic, _Ctor

    formula = _peel_double_negation(formula)
    if (
        not isinstance(formula, _Atomic)
        or formula.name != "py.truthy"
        or len(formula.args) != 1
    ):
        return None
    call = formula.args[0]
    if not isinstance(call, _Ctor):
        return None
    if call.name != "call:matches" and not call.name.endswith(".matches"):
        return None
    if not any(_term_contains_ctor(arg, "python:exit_value") for arg in call.args):
        return None
    return call


def _matches_call_of_exit_value(formula):
    """A matches() citation, including the unique matches() conjunct of an ``and``.

    Nested ``if exc_type is None`` / ``if not matches()`` / ``return True``
    produces ``not (exc_type is None) and matches()`` as the True-return
    formula. Several distinct matches() calls stay unclassified.
    """
    from sugar_lift_py_tests.ir import _Connective

    formula = _peel_double_negation(formula)
    if isinstance(formula, _Connective) and formula.kind == "and":
        found = []
        for operand in formula.operands:
            call = _matches_call_of_exit_value(operand)
            if call is not None and call not in found:
                found.append(call)
        return found[0] if len(found) == 1 else None
    return _direct_matches_call_of_exit_value(formula)


def _term_contains_term(haystack, needle):
    if haystack == needle:
        return True
    args = getattr(haystack, "args", None) or getattr(haystack, "operands", None)
    if not args:
        return False
    return any(_term_contains_term(arg, needle) for arg in args)


def _keyword_supplied_value(behavior, field_name):
    """The unique ``**kwargs`` value stored under ``field_name``, if any."""
    from sugar_lift_py_tests.floor.dict_value import DictValue
    from sugar_lift_py_tests.floor.string_value import StringValue

    if not field_name:
        return None
    candidates = []
    for actual in behavior.formal_actual_values:
        if type(actual) is not DictValue:
            continue
        matching = [
            value
            for key, value in actual.entries
            if type(key) is StringValue and key.value == field_name
        ]
        if len(matching) > 1:
            return None
        if len(matching) == 1:
            candidates.append(matching[0])
    return candidates[0] if len(candidates) == 1 else None


def _keyword_entry_cited_by_field(behavior, field_name, receiver=None):
    """Cite a stored field that arrived as a unique ``**kwargs`` entry.

    Factory ``raises(expected, *args, **kwargs)`` does not name ``match``.
    The pattern is the unique dict entry whose string key is the field name
    and whose value is the stored field, or whose term is uniquely contained
    in the stored field (the unique string argument of ``re.compile(match)``
    is still that kwargs entry; the compile call is not itself the string).
    That is a variadic keyword entry, not a named formal and not
    NoMessagePattern.
    """
    from sugar_lift_py_tests.floor.dict_value import DictValue
    from sugar_lift_py_tests.floor.none_value import NoneValue
    from sugar_lift_py_tests.floor.string_value import StringValue

    if not field_name:
        return None
    field = _receiver_field_value(behavior, field_name, receiver=receiver)
    if field is None or isinstance(field, NoneValue):
        return None
    field_term = field.to_term(owner=behavior.resolved_object_cid)
    candidates = []
    for index, actual in enumerate(behavior.formal_actual_values):
        if type(actual) is not DictValue:
            continue
        matching = [
            key.value
            for key, value in actual.entries
            if type(key) is StringValue
            and key.value == field_name
            and (
                value == field
                or _term_contains_term(
                    field_term,
                    value.to_term(owner=behavior.resolved_object_cid),
                )
            )
        ]
        if len(matching) > 1:
            return None
        if len(matching) == 1:
            candidates.append(
                VariadicKeywordEntryProjectionV1(index, matching[0])
            )
    return candidates[0] if len(candidates) == 1 else None


def _formal_index_cited_by_field(behavior, field_name, actual_terms):
    from sugar_lift_py_tests.floor.none_value import NoneValue

    field = _receiver_field_value(behavior, field_name)
    if field is None or isinstance(field, NoneValue):
        return None
    haystack = field.to_term(owner=behavior.resolved_object_cid)
    candidates = {
        index
        for index, term in enumerate(actual_terms)
        if _term_contains_term(haystack, term)
    }
    return next(iter(candidates)) if len(candidates) == 1 else None


def _formal_index_for_matches_expected(formula, behavior, actual_terms):
    if _matches_call_of_exit_value(formula) is None:
        return None
    return _formal_index_cited_by_field(
        behavior, "expected_exceptions", actual_terms
    )


def _formal_index_for_matches_message(formula, behavior, actual_terms):
    if _matches_call_of_exit_value(formula) is None:
        return None
    return _formal_index_cited_by_field(behavior, "match", actual_terms)


def _true_return_guards(exit_set):
    true_guards = []
    for other in exit_set.exits:
        if not isinstance(other, Completed):
            continue
        block = other.value
        if not isinstance(block, BlockValue) or not block.statements:
            continue
        last = block.statements[-1]
        if isinstance(last, ReturnValue) and _exact_bool_literal(last.value) is True:
            true_guards.append(other.guard)
    return true_guards


def _conjuncts(formula):
    from sugar_lift_py_tests.ir import _Connective

    formula = _peel_double_negation(formula)
    if isinstance(formula, _Connective) and formula.kind == "and":
        items = []
        for operand in formula.operands:
            items.extend(_conjuncts(operand))
        return items
    return [formula]


def _matches_conjunct_polarity(formula):
    """``pos`` if formula is matches(); ``neg`` if it is not matches()."""
    from sugar_lift_py_tests.ir import _Connective

    formula = _peel_double_negation(formula)
    if _direct_matches_call_of_exit_value(formula) is not None:
        return "pos"
    if (
        isinstance(formula, _Connective)
        and formula.kind == "not"
        and len(formula.operands) == 1
        and _direct_matches_call_of_exit_value(
            _peel_double_negation(formula.operands[0])
        )
        is not None
    ):
        return "neg"
    return None


def _halt_complements_true_return(face, exit_set):
    """True when ``face`` is the complement of the unique ``return True`` arm."""
    from sugar_lift_py_tests.outcome import Halted
    from sugar_lift_py_tests.outcome.exit_set import complement_guard

    if not isinstance(face, Halted):
        return False
    true_guards = _true_return_guards(exit_set)
    if len(true_guards) != 1:
        return False
    return face.guard == complement_guard(true_guards[0])


def _halt_negates_matches_conjunct_of_true_return(face, exit_set):
    """True when halt and the unique return-True arm share every conjunct
    except a matches() / not-matches() pair.

    Nested ``if exc_type is None: fail(); if not matches(): raise; return True``
    produces halt guard ``not A and not matches()`` and True guard
    ``not A and matches()``. Those are not global complements
    (``A or not matches()``), but they are the same partition's match-failed
    halt.
    """
    from sugar_lift_py_tests.outcome import Halted

    if not isinstance(face, Halted):
        return False
    true_guards = _true_return_guards(exit_set)
    if len(true_guards) != 1:
        return False
    true_parts = _conjuncts(true_guards[0])
    halt_parts = _conjuncts(face.guard)
    if (
        sum(1 for part in true_parts if _matches_conjunct_polarity(part) == "pos")
        != 1
        or sum(1 for part in halt_parts if _matches_conjunct_polarity(part) == "neg")
        != 1
    ):
        return False
    true_rest = [
        part for part in true_parts if _matches_conjunct_polarity(part) != "pos"
    ]
    halt_rest = [
        part for part in halt_parts if _matches_conjunct_polarity(part) != "neg"
    ]
    unused = list(halt_rest)
    for item in true_rest:
        try:
            unused.remove(item)
        except ValueError:
            return False
    return not unused


def _completed_faces_have_bodyless_free_calls(exit_set):
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue

    for face in exit_set.exits:
        if not isinstance(face, Completed):
            continue
        statements = getattr(getattr(face, "value", None), "statements", ())
        for statement in statements:
            if (
                isinstance(statement, CallSiteValue)
                and statement.body is None
                and getattr(statement, "runtime_dispatch_receiver", None) is None
            ):
                return True
    return False


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
                # ``exc_type is None`` compares against the language
                # singleton, not a factory formal that happens to be None
                # (``func=None``).
                if _term_is_none_singleton(term):
                    continue
                candidates.add(index)
    return next(iter(candidates)) if len(candidates) == 1 else None


def _term_is_none_singleton(term):
    from sugar_lift_py_tests.ir import _Ctor

    return isinstance(term, _Ctor) and term.name == "None" and not term.args


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
            from sugar_lift_py_tests.context_manager_contract import (
                ConstructedDefaultV1,
                ContextManagerContractError,
                LiteralDefaultV1,
            )

            try:
                default = LiteralDefaultV1(raw)
            except ContextManagerContractError:
                default = ConstructedDefaultV1(raw)
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


def _qualified_enrollment_coordinate(
    path,
    *,
    source_workspace_root,
    distribution: str | None,
) -> str:
    """Qualify a source seat from authenticated authority, never path guesses."""
    from pathlib import Path

    if not distribution:
        raise ValueError(
            "source workspace distribution authority is required; "
            "refusing to infer it from a relative path segment"
        )
    try:
        relative = (
            Path(path).resolve().relative_to(Path(source_workspace_root).resolve())
        )
    except ValueError as error:
        raise ValueError(
            "source seat is outside the authenticated source workspace: "
            f"path={path} source_workspace_root={source_workspace_root}"
        ) from error
    parts = relative.parts
    # An install-root seat already carries its distribution prefix; a package
    # root seat does not. Preserve one canonical distribution-qualified form.
    if parts and parts[0] == distribution:
        return "/".join(parts)
    return "/".join((distribution, *parts))


class MissingEnrolledDistributionRoster(ValueError):
    """The caller omitted the authenticated population authority."""


def populate_source_derived_resource_refs(
    source_file,
    *,
    root,
    path,
    distribution_index=None,
    artifact_graph_cache: dict | None = None,
    session=None,
    selected_coordinates: frozenset | None = None,
    source_workspace_root=None,
    distribution: str | None = None,
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
    from sugar_lift_py_tests.import_binding import (
        authenticated_import_use_receipts,
        authenticated_import_value_use_receipts,
    )
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
    if source_workspace_root is not None:
        _qualified_enrollment_coordinate(
            path,
            source_workspace_root=source_workspace_root,
            distribution=distribution,
        )
    if distribution is not None:
        from .resolution_session import enrolled_population_roster

        # Never NARROW a session's declared population mid-walk: the walk
        # session was minted with the full roster; this open contributes its
        # corpus distribution to it.
        session.enrolled_distributions = enrolled_population_roster(
            distribution
        ) | (session.enrolled_distributions or frozenset())
    elif session.enrolled_distributions is None:
        raise MissingEnrolledDistributionRoster(
            "missing-enrolled-distribution-roster: distribution authority was not "
            "supplied; refusing to infer an enrolled population from a path segment"
        )
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
    value_receipts, _ = authenticated_import_value_use_receipts(
        Path(root),
        Path(path),
        source_file.unit.source,
        source_file.unit.source_cid,
        module_identities={},
        module=source_file.root,
    )
    selected_arms: dict = {}
    uses = _projected_manager_call_uses(source_file, selected_arms)
    if selected_coordinates is not None:
        # A branch-selected With item is selected by its own use site; its
        # arms' calls are derived with it.
        arm_owner = {
            arm: use_site
            for use_site, arms in selected_arms.items()
            for arm in arms
        }
        uses = {
            key: value
            for key, value in uses.items()
            if value[0] in selected_coordinates
            or arm_owner.get(value[0]) in selected_coordinates
        }

    def _receipt_site_key(receipt):
        raw_site = receipt.use["useSite"]
        return (
            raw_site["sourceCid"],
            raw_site["startLine"],
            raw_site["startCol"],
            raw_site["endLine"],
            raw_site["endCol"],
        )

    def _unique_receipts_by_site(rows, *, owner: str):
        indexed = {}
        for row in rows:
            key = _receipt_site_key(row)
            if key in indexed:
                from sugar_source_tree.panic import BackendDefect

                raise BackendDefect(
                    blame=Path(path),
                    owner=owner,
                    observed=f"duplicate authenticated import receipts at {key}",
                    requested="one authenticated import receipt per physical coordinate",
                    fix="repair lexical receipt enrollment uniqueness; never choose by order",
                )
            indexed[key] = row
        return indexed

    call_receipts_by_site = _unique_receipts_by_site(
        receipts,
        owner="manager_summary_derivation imported manager call receipt pairing",
    )
    value_receipts_by_site = _unique_receipts_by_site(
        value_receipts,
        owner="manager_summary_derivation imported manager value receipt pairing",
    )
    paired_receipts = []
    paired_keys = set()
    for call_key, selected in uses.items():
        _, call, _ = selected
        source_cid = call.unit.source_cid
        # The closed call-contract door remains authoritative whenever it
        # admitted the full Call.  Only a keyword-bearing direct Name that it
        # deliberately excludes may fall back to the independently minted
        # value-use receipt at the exact callee occurrence.  No spelling or
        # target-symbol join is admissible here.
        receipt = call_receipts_by_site.get((source_cid, *call_key))
        if receipt is None and call.func.kind == "Name" and call.keywords:
            callee_span = call.func.line_col_span()
            callee_key = (
                source_cid,
                callee_span.start_line,
                callee_span.start_col,
                callee_span.end_line,
                callee_span.end_col,
            )
            receipt = value_receipts_by_site.get(callee_key)
        if receipt is not None:
            paired_receipts.append((receipt, selected))
            paired_keys.add(call_key)

    graphs = {} if artifact_graph_cache is None else artifact_graph_cache
    # Seed from session so tops already resolved in frame/prefix projection
    # are not re-asked (warnings/re/inspect ×21 on test_pandas).
    if session.enabled:
        for top, graph in session.dependency_graphs.items():
            graphs.setdefault(top, graph)
    for receipt, selected in paired_receipts:
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
            except DependencyArtifactAuthenticationError as exc:
                from .language_owned_c_export import interpreter_owned_c_type_export

                # No artifact, because no source: the callee is a C type an
                # interpreter-owned module exports (``mmap.mmap``).  That is a
                # positive runtime-identity fact, not the authentication
                # failure read as one, so the manager is cited, naming its
                # callee.  Anything else (an absent module, a Python object)
                # keeps the gap.
                _install_derivation_gap(
                    context,
                    coordinate,
                    receipt,
                    (
                        "call-target-c-type-without-source"
                        if interpreter_owned_c_type_export(receipt.target_symbol)
                        else "no-derived-contract"
                    ),
                    f"dependency artifact authentication failed for {top_level}: {exc}",
                )
                continue
            graphs[top_level] = graph
            if session.enabled:
                session.dependency_graphs[top_level] = graph
        resolved = resolve_import_binding(receipt, graph=graph, session=session)
        if not isinstance(resolved, ResolvedPythonObjectV1):
            from .language_owned_io_resource import mint_language_owned_io_resource_ref

            owned = mint_language_owned_io_resource_ref(coordinate, receipt, resolved)
            if owned is None:
                from .language_owned_c_manager import (
                    mint_language_owned_c_manager_ref,
                )

                owned = mint_language_owned_c_manager_ref(coordinate, receipt, resolved)
            if owned is not None:
                context.source_derived_contract_refs[coordinate] = owned
                continue
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
            # Call operands authenticate their values, not the callee's
            # enter/exit behavior. Preserve this construction refusal.
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

        def _actual_sugar(node, *, formal_name: str | None = None):
            # Authentication is compositional: construct exception operands
            # through their existing Sugar owners before reducing the tuple.
            from dataclasses import replace

            from sugar_lift_py_tests.sugar.authenticated_exception_type_sugar import (
                AuthenticatedExceptionTypeSugar,
            )
            from sugar_lift_py_tests.sugar.collection_sugar import TupleSugar
            from sugar_source_tree.nodes import Attribute, Name, Tuple_

            surface = node.sugar()
            if isinstance(node, Tuple_) and isinstance(surface, TupleSugar):
                return replace(
                    surface,
                    elements=tuple(
                        _actual_sugar(element, formal_name=formal_name)
                        for element in node.elts
                    ),
                )
            if isinstance(node, Name):
                builtin = actual_ctx.temporal.value_if_bound(node.id)
                if builtin is not None:
                    return surface
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
                        surface,
                        identity,
                        mro,
                        site=node.fragment,
                        class_value=class_value,
                    )
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
                    return AuthenticatedExceptionTypeSugar(
                        surface,
                        testimony.identity,
                        testimony.ancestry,
                        site=node.fragment,
                        class_value=class_value,
                    )
                identity = node.unit.imported_exception_type_identity(node)
                if identity is not None:
                    qualified = getattr(identity.args[1], "value", None)
                    if isinstance(qualified, str) and qualified:
                        # The authenticated Sugar owns floor construction; the
                        # imported coordinate need not re-evaluate its module.
                        return AuthenticatedExceptionTypeSugar(
                            surface, identity, site=node.fragment
                        )
            return surface

        actuals = []
        positional_sugars = []
        actual_refusal = None
        for index, node in enumerate(call.args):
            formal_name = (
                frame_parameters[index] if index < len(frame_parameters) else None
            )
            actual_sugar = _actual_sugar(node, formal_name=formal_name)
            try:
                outcome = _completed_actual(actual_sugar.desugar(actual_ctx))
            except SugarNotWritten as exc:
                # The actual's own named refusal (an undecided ``self.x``
                # receiver) is this With's refusal, never a file terminal.
                actual_refusal = exc
                actuals = []
                break
            if not isinstance(outcome, Complete):
                actuals = []
                break
            positional_sugars.append(actual_sugar)
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
        keyword_sugars = []
        if len(actuals) == len(call.args):
            for keyword in call.keywords:
                if keyword.arg is None:
                    keyword_actuals = []
                    actuals = []
                    break
                actual_sugar = _actual_sugar(keyword.value, formal_name=keyword.arg)
                try:
                    outcome = _completed_actual(actual_sugar.desugar(actual_ctx))
                except SugarNotWritten as exc:
                    actual_refusal = exc
                    keyword_actuals = []
                    actuals = []
                    break
                if not isinstance(outcome, Complete):
                    keyword_actuals = []
                    actuals = []
                    break
                keyword_sugars.append((keyword.arg, actual_sugar))
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
        if actual_refusal is not None or len(actuals) != len(call.args):
            _install_derivation_gap(
                context,
                coordinate,
                receipt,
                "incomplete-call-actuals",
                *(
                    ()
                    if actual_refusal is None
                    else (str(getattr(actual_refusal, "observed", actual_refusal)),)
                ),
            )
            continue
        from sugar_lift_py_tests.context_manager_contract import (
            ContextManagerContractError,
        )

        try:
            behavior = construct_manager_behavior(
                resolved,
                graph=graph,
                actuals=tuple(actuals),
                keyword_actuals=tuple(keyword_actuals),
                call_site=call.fragment,
                session=session,
            )
        except (SugarNotWritten, TypeError, ContextManagerContractError) as exc:
            kind, detail = _populate_body_defect_kind_detail(exc)
            _install_derivation_gap(
                context,
                coordinate,
                receipt,
                kind,
                detail,
            )
            continue
        from .manager_construction import (
            ConstructedManagerBehaviorV1,
            PartitionedManagerBehaviorV1,
        )
        from .manager_protocol_construction import ConstructedManagerProtocolV1

        if isinstance(behavior, PartitionedManagerBehaviorV1):
            # The factory returns managers of more than one kind on its faces:
            # construct each, enter each under its own guard (#7669).
            _publish_manager_face_partition(
                context,
                coordinate,
                behavior,
                receipt=receipt,
                exit_face_id=exit_face_id,
                session=session,
                graph=graph,
                dependency_graphs=graphs,
                distribution_index=distribution_index,
                positional_sugars=tuple(positional_sugars),
                keyword_sugars=tuple(keyword_sugars),
            )
            continue
        if not isinstance(behavior, ConstructedManagerBehaviorV1):
            # Stage-keyed residual — never collapse assertion-membrane mass into
            # a single opaque label, and never fuse the stage with its data:
            # `value-call-target` is the key, the callee names are the row.
            kind, detail = _gap_kind_and_detail(behavior)
            if (
                kind == "call-target-off-population"
                and detail
                and _seat_off_population_citation(
                    context,
                    coordinate,
                    detail,
                    kind,
                    receipt.demand.get("cid", receipt.use["cid"]),
                )
            ):
                # The factory returned an off-population callee's result: the
                # citation names THAT callee, not the factory (#7667).
                continue
            _install_derivation_gap(context, coordinate, receipt, kind, detail)
            continue
        try:
            protocol = construct_manager_protocol(behavior, exit_face_id=exit_face_id)
        except (SugarNotWritten, TypeError) as exc:
            # Call operands authenticate their values, not the callee's
            # enter/exit behavior. Preserve this construction refusal.
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
        from sugar_lift_py_tests.context_manager_resolution import (
            SourceCallActualSugarsV1,
        )

        _publish_class_protocol_native_definitions(context, coordinate, behavior)
        context.source_derived_contract_refs[coordinate] = (
            SourceDerivedContextManagerRefV1(
                coordinate,
                summary.summary_cid,
                summary.semantics,
                summary.import_signature,
                protocol,
                call_actual_sugars=(
                    SourceCallActualSugarsV1(
                        coordinate,
                        tuple(positional_sugars),
                        tuple(keyword_sugars),
                        behavior.source_call_frame,
                    )
                    if isinstance(summary.semantics, ProtocolResourceSemanticsV1)
                    else None
                ),
            )
        )
        _seat_projected_manager_call_frame(context, coordinate, call, behavior)

    # ``with open(...)`` first: it depends on no other row, and a same-module
    # manager whose own body opens a file (``@contextmanager def g(): with
    # open(p) as f: yield f``) builds its frame from that nested row, so it
    # must be seated before any same-module reader reads the body (#7732).
    _populate_builtin_c_manager_uses(context, uses)

    # A callee Name assigned in every arm of a selection (``m = a.A`` /
    # ``elif``: ``m = b.B`` / ``with m(...)``) has no receipt at the call, but
    # each ARM has a value receipt at its own occurrence. Derive the partition
    # member by member through the same import door; a partition of cited
    # members is a cited partition.
    _populate_assigned_partition_manager_uses(
        source_file,
        context,
        uses,
        paired_keys=paired_keys,
        value_receipts_by_site=value_receipts_by_site,
        graphs=graphs,
        session=session,
        distribution_index=distribution_index,
    )

    # Same-module ClassDef managers have no import receipt. Derive them through
    # module_direct_bindings → Call.force_floor → protocol → summary — the same
    # publication door as import-backed ClassDef CMs. Uncovered uses stay empty
    # for With.require (L3d) to panic.
    _populate_same_module_class_manager_uses(source_file, context, uses)
    _populate_same_module_generator_manager_uses(
        context,
        uses,
        session=session,
        graphs=graphs,
        distribution_index=distribution_index,
    )
    _populate_same_module_factory_manager_uses(
        context,
        uses,
        value_receipts_by_site,
        graphs=graphs,
        session=session,
        distribution_index=distribution_index,
    )
    _populate_formal_selected_manager_uses(
        source_file, context, selected_coordinates=selected_coordinates
    )
    _floor_language_owned_module_calls(
        context,
        call_receipts_by_site,
        value_receipts_by_site,
        manager_use_keys=frozenset(uses),
        graphs=graphs,
        session=session,
        distribution_index=distribution_index,
    )
    _floor_language_owned_module_type_reads(
        source_file,
        context,
        call_receipts_by_site,
        value_receipts_by_site,
        graphs=graphs,
        session=session,
        distribution_index=distribution_index,
    )
    _populate_runtime_selected_head_uses(
        source_file, context, selected_coordinates=selected_coordinates
    )
    _seat_selected_manager_refs(context, selected_arms, selected_coordinates)
    _rewrite_installed_generator_frames(context)


def _seat_selected_manager_refs(context, selected_arms, selected_coordinates) -> None:
    """Move each branch-selected item's arm resolutions into its one row.

    The arms were derived at their own call coordinates, which are not With
    items; leaving them there counted one With item once per arm.
    """
    from sugar_lift_py_tests.context_manager_resolution import (
        SelectedContextManagerRefV1,
    )

    table = context.source_derived_contract_refs
    for use_site, arms in selected_arms.items():
        if selected_coordinates is not None and use_site not in selected_coordinates:
            continue
        table[use_site] = SelectedContextManagerRefV1(
            use_site=use_site,
            arms=tuple((arm, table.pop(arm, None)) for arm in arms),
        )


def _floor_language_owned_module_type_reads(
    source_file,
    context,
    call_receipts_by_site,
    value_receipts_by_site,
    *,
    graphs,
    session,
    distribution_index,
) -> None:
    """Seat a C class at this module's own non-call reads (``io.TextIOWrapper``).

    ``isinstance(handle, io.TextIOWrapper)`` reads the class as a value.  The
    consumer module's own value reads were never seated, so the read stood as
    an unknown attribute and the isinstance as a dynamic type operand.  When
    the read resolves to an ``artifact-module-absent`` export whose runtime
    object is a C heap class of an interpreter-owned module, the read is that
    language-owned C class (the type rule, never the C-function rule).  A read
    that is a call's callee stays with the call floor.
    """
    from sugar_lift_py_tests.context_manager_resolution import (
        SourceFragmentCoordinateV1,
    )
    from sugar_lift_py_tests.floor.language_owned_c_type import (
        LanguageOwnedCTypeValue,
    )

    from .dependency_artifact import (
        DependencyArtifactAuthenticationError,
        authenticate_dependency_top_level,
        resolve_import_binding,
    )
    from .language_owned_c_export import floor_artifact_module_absent_export

    unit = source_file.unit
    callee_starts = {
        (source_cid, start_line, start_col)
        for source_cid, start_line, start_col, *_rest in call_receipts_by_site
    }
    for site_key, receipt in value_receipts_by_site.items():
        source_cid, start_line, start_col, end_line, end_col = site_key
        if source_cid != unit.source_cid:
            continue
        if (source_cid, start_line, start_col) in callee_starts:
            continue
        span = (start_line, start_col, end_line, end_col)
        if unit.import_value_use_resolution(span) is not None:
            continue
        top_level = receipt.target_symbol.removeprefix("python:").split(".", 1)[0]
        graph = graphs.get(top_level)
        if graph is None and session.enabled:
            graph = session.dependency_graphs.get(top_level)
        if graph is None:
            try:
                graph = authenticate_dependency_top_level(
                    top_level, distribution_index=distribution_index
                )
            except DependencyArtifactAuthenticationError:
                continue
            graphs[top_level] = graph
            if session.enabled:
                session.dependency_graphs[top_level] = graph
        imported = resolve_import_binding(receipt, graph=graph, session=session)
        floored = floor_artifact_module_absent_export(imported)
        if type(floored) is not LanguageOwnedCTypeValue:
            continue
        unit.seat_import_value_use_resolution(span, receipt, source_cid=source_cid)
        context.source_import_value_resolutions[
            SourceFragmentCoordinateV1(source_cid, *span)
        ] = floored


def _floor_language_owned_module_calls(
    context,
    call_receipts_by_site,
    value_receipts_by_site,
    *,
    manager_use_keys,
    graphs,
    session,
    distribution_index,
) -> None:
    """Hang the language-owned floor on this module's own imported calls.

    Frame projection already floors an imported call inside a dependency
    frame (``manager_construction``); the consumer module's own calls never
    pass through it, so ``return decimal.getcontext()`` stood as a bodiless
    ``CallSiteValue`` that silently completed. The same door applies here:
    the exact call receipt is resolved through the authenticated import
    graph, and only an ``artifact-module-absent`` export whose runtime object
    is a C function (or ContextVar) is floored, at its exact Call span. The
    floor's application is the two-faced C-call law. With-head manager calls
    keep their own contract and are never floored here.
    """
    from .dependency_artifact import (
        DependencyArtifactAuthenticationError,
        ResolvedPythonObjectV1,
        authenticate_dependency_top_level,
        resolve_import_binding,
    )
    from .language_owned_c_export import floor_language_owned_import_use
    from .manager_construction import _language_owned_call_site_key

    for site_key, receipt in call_receipts_by_site.items():
        source_cid, *span = site_key
        if tuple(span) in manager_use_keys:
            continue
        top_level = receipt.target_symbol.removeprefix("python:").split(".", 1)[0]
        graph = graphs.get(top_level)
        if graph is None and session.enabled:
            graph = session.dependency_graphs.get(top_level)
        if graph is None:
            try:
                graph = authenticate_dependency_top_level(
                    top_level, distribution_index=distribution_index
                )
            except DependencyArtifactAuthenticationError:
                # No authenticated graph: no runtime identity to key on. The
                # call keeps its ordinary (unfloored) construction.
                continue
            graphs[top_level] = graph
            if session.enabled:
                session.dependency_graphs[top_level] = graph
        imported = resolve_import_binding(receipt, graph=graph, session=session)
        if isinstance(imported, ResolvedPythonObjectV1) and imported.definition.kind in (
            "function",
            "class",
        ):
            # Source-defined callee (a function, or a class whose construction
            # runs its unprojected __new__/__init__): its body is never
            # projected at this module's own call, so the call is not total.
            # Seat the may-raise testimony at the exact Call span; a call that
            # does carry a projected body at construction ignores it.
            from sugar_lift_py_tests.source_call_resolution import (
                UnprojectedSourceCallV1,
            )

            context.unprojected_source_calls[
                _language_owned_call_site_key(source_cid, receipt.use["useSite"])
            ] = UnprojectedSourceCallV1(
                imported.module_name,
                imported.definition.name,
                imported.definition.kind,
                imported.cid,
            )
            continue
        if isinstance(imported, ResolvedPythonObjectV1):
            continue
        # The value receipt at the exact callee occurrence (same binding,
        # same target symbol, same start, inside this Call) carries the
        # member path a ContextVar method floor needs.
        call_site = receipt.use["useSite"]
        callee_receipts = [
            value
            for value in value_receipts_by_site.values()
            if value.target_symbol == receipt.target_symbol
            and value.import_binding.cid == receipt.import_binding.cid
            and value.use["useSite"]["sourceCid"] == source_cid
            and value.use["useSite"]["startLine"] == call_site["startLine"]
            and value.use["useSite"]["startCol"] == call_site["startCol"]
            and (value.use["useSite"]["endLine"], value.use["useSite"]["endCol"])
            < (call_site["endLine"], call_site["endCol"])
        ]
        value_receipt = callee_receipts[0] if len(callee_receipts) == 1 else None
        floored = floor_language_owned_import_use(
            imported,
            value_receipt if value_receipt is not None else receipt,
            graph=graph,
            session=session,
        )
        if floored is None:
            continue
        context.language_owned_call_floors[
            _language_owned_call_site_key(source_cid, receipt.use["useSite"])
        ] = floored


def _rewrite_installed_generator_frames(context) -> None:
    """Rewrite seated generator frames after contract refs are published.

    ``_publish_generator_backed_resource_contract`` only rewrites a
    protocol-backing copy, and only when decorator coordinates exist. A bare
    generator (pandas ``assert_produces_warning``, a local ``yield`` manager)
    is consumed from ``source_call_frames``. Apply the cited-opaque rewrite
    to those live frames once the manager-source refs are seated.

    ``bind_node_actuals`` re-emits steps from the FunctionDef, which would
    drop the rewrite; wrap those frames so bind reapplies it.
    """
    frames = getattr(context, "source_call_frames", None)
    if not frames:
        return
    for coordinate, frame in list(frames.items()):
        if getattr(frame, "generator_steps", None) is None:
            continue
        rewritten = _frame_with_nested_manager_steps(frame, ())
        frames[coordinate] = _as_rewriting_generator_frame(rewritten)


def _rewriting_generator_frame_class():
    from sugar_lift_py_tests.source_call_frame import SourceVisibleCallFrameV1

    cached = getattr(_rewriting_generator_frame_class, "_cls", None)
    if cached is not None:
        return cached

    class _GeneratorFrameWithCitedOpaqueRewriteV1(SourceVisibleCallFrameV1):
        """A source-visible frame that reapplies cited-opaque With rewrite after bind."""

        def bind_node_actuals(self, *args, **kwargs):
            bound = super().bind_node_actuals(*args, **kwargs)
            rewritten = _frame_with_nested_manager_steps(bound, ())
            return _as_rewriting_generator_frame(rewritten)

    _rewriting_generator_frame_class._cls = _GeneratorFrameWithCitedOpaqueRewriteV1
    return _GeneratorFrameWithCitedOpaqueRewriteV1


def _as_rewriting_generator_frame(frame):
    """Keep a bind hook on a live source-visible generator frame."""
    from dataclasses import fields

    from sugar_lift_py_tests.source_call_frame import SourceVisibleCallFrameV1

    cls = _rewriting_generator_frame_class()
    if isinstance(frame, cls):
        return frame
    if not isinstance(frame, SourceVisibleCallFrameV1):
        return frame
    values = {item.name: getattr(frame, item.name) for item in fields(frame) if item.init}
    return cls(**values)


def _enclosing_function(source_file, node):
    """The innermost FunctionDef whose body contains ``node``, or None."""
    innermost = None
    innermost_span = None
    for function in source_file.functions():
        if not any(candidate is node for candidate in function.walk()):
            continue
        span = function.line_col_span()
        key = (span.start_line, span.start_col, -span.end_line, -span.end_col)
        if innermost_span is None or key > innermost_span:
            innermost, innermost_span = function, key
    return innermost


def _name_binders(function, name: str):
    """Every statement in ``function`` that binds ``name``, by shape.

    Returns ``(assignments, other_binders)``: the single-target ``Assign``
    arms whose RHS may carry an import value receipt, and every other binder
    (augmented / annotated assignment, loop or with target, walrus, nested
    def/class, global/nonlocal, a formal of the same name). Any entry in the
    second list means the name's reaching value is not the assignment arms
    alone, so the partition is not authenticated by them.
    """
    from sugar_source_tree.nodes import (
        AnnAssign,
        Assign,
        AsyncFor,
        AsyncWith,
        AugAssign,
        ClassDef,
        For,
        FunctionDef,
        Global,
        Name,
        NamedExpr,
        Nonlocal,
        With,
    )

    def names_in(target) -> set:
        if isinstance(target, Name):
            return {target.id}
        found = set()
        for child in getattr(target, "elts", ()) or ():
            found |= names_in(child)
        value = getattr(target, "value", None)
        if getattr(target, "kind", None) == "Starred" and value is not None:
            found |= names_in(value)
        return found

    assignments = []
    other = []
    if any(param.name == name for param in function.params):
        other.append(function)
    for node in function.walk():
        if node is function:
            continue
        if isinstance(node, Assign):
            if (
                len(node.targets) == 1
                and isinstance(node.targets[0], Name)
                and node.targets[0].id == name
            ):
                assignments.append(node)
            elif any(name in names_in(target) for target in node.targets):
                other.append(node)
        elif isinstance(node, AnnAssign):
            # ``m: Callable`` declares; it binds nothing (pandas/_testing/_io.py:94
            # refused the reproducer through exactly this line on the first
            # sealed board). ``m: T = a.A`` is an arm like any Assign to ``m``.
            if node.value is None or not (
                isinstance(node.target, Name) and node.target.id == name
            ):
                if name in names_in(node.target) and node.value is not None:
                    other.append(node)
                continue
            assignments.append(node)
        elif isinstance(node, (AugAssign, NamedExpr)):
            if name in names_in(node.target):
                other.append(node)
        elif isinstance(node, (For, AsyncFor)):
            if name in names_in(node.target):
                other.append(node)
        elif isinstance(node, (With, AsyncWith)):
            for item in node.items:
                if item.optional_vars is not None and name in names_in(
                    item.optional_vars
                ):
                    other.append(node)
        elif isinstance(node, (FunctionDef, ClassDef)):
            if node.name == name:
                other.append(node)
        elif isinstance(node, (Global, Nonlocal)):
            if name in tuple(node.names):
                other.append(node)
    return assignments, other


def _populate_assigned_partition_manager_uses(
    source_file,
    context,
    uses,
    *,
    paired_keys,
    value_receipts_by_site,
    graphs,
    session,
    distribution_index,
) -> None:
    """Derive ``with m(...)`` where ``m`` is assigned an import value per arm.

    Reproducer (pandas/_testing/_io.py): ``compress_method`` is bound to
    ``gzip.GzipFile`` / ``bz2.BZ2File`` / ... in an if/elif chain, then used
    once as the manager callee. The call has no receipt (its callee is a local
    Name), so the demand table left it ``runtime-selected``. Every arm,
    however, is an authenticated import value with its own receipt.

    Law: the reaching value of the callee is exactly the set of assignment
    arms when nothing else binds the name in the function. Each arm resolves
    through the ordinary import door. The membrane's off-population refusal
    cites the member (the same seat a direct ``with gzip.GzipFile(...)`` gets);
    a partition whose members are all cited is minted as one
    ``PartitionedOpaqueCitedContextManagerRefV1``. Anything else stays a loud
    typed gap naming the arm that refused -- never ``runtime-selected``.
    """
    from sugar_lift_py_tests.context_manager_resolution import (
        OpaqueSourceCallObligationV1,
        SourceFragmentCoordinateV1,
        mint_opaque_cited_context_manager_ref,
        mint_partitioned_opaque_cited_context_manager_ref,
        opaque_source_call_roster_of,
    )
    from sugar_source_tree.nodes import Name

    from .dependency_artifact import (
        DependencyArtifactAuthenticationError,
        ResolvedPythonObjectV1,
        authenticate_dependency_top_level,
        resolve_import_binding,
    )
    from .manager_construction import (
        ManagerConstructionGapV1,
        resolve_source_visible_frame,
    )

    def arm_coordinate(node):
        span = node.value.line_col_span()
        return SourceFragmentCoordinateV1(
            node.unit.source_cid,
            span.start_line,
            span.start_col,
            span.end_line,
            span.end_col,
        )

    def arm_receipt(node):
        span = node.value.line_col_span()
        return value_receipts_by_site.get(
            (
                node.unit.source_cid,
                span.start_line,
                span.start_col,
                span.end_line,
                span.end_col,
            )
        )

    def graph_for(receipt):
        top_level = receipt.target_symbol.removeprefix("python:").split(".", 1)[0]
        graph = graphs.get(top_level)
        if graph is None and session.enabled:
            graph = session.dependency_graphs.get(top_level)
        if graph is None:
            graph = authenticate_dependency_top_level(
                top_level, distribution_index=distribution_index
            )
            if session.enabled:
                session.dependency_graphs[top_level] = graph
        graphs[top_level] = graph
        return graph

    for call_key, (coordinate, call, _exit_face_id) in uses.items():
        if call_key in paired_keys:
            continue
        if coordinate in context.source_derived_contract_refs:
            continue
        if not isinstance(call.func, Name):
            continue
        function = _enclosing_function(source_file, call)
        if function is None:
            continue
        name = call.func.id
        assignments, other_binders = _name_binders(function, name)
        arms = [(node, arm_receipt(node)) for node in assignments]
        receipted = [(node, receipt) for node, receipt in arms if receipt is not None]
        if not receipted:
            # Not this law's shape: no arm is an import value.
            continue
        first_receipt = receipted[0][1]
        if other_binders:
            where = ", ".join(
                f"{type(binder).__name__}@{binder.line_col_span().start_line}"
                for binder in other_binders
            )
            _install_derivation_gap(
                context,
                coordinate,
                first_receipt,
                "partition-member-unauthenticated",
                f"{name!r} is also bound by {where}; the assignment arms are not "
                "its whole reaching value",
            )
            continue
        unreceipted = [node for node, receipt in arms if receipt is None]
        if unreceipted:
            where = ", ".join(str(node.line_col_span().start_line) for node in unreceipted)
            _install_derivation_gap(
                context,
                coordinate,
                first_receipt,
                "partition-member-unauthenticated",
                f"{name!r} arm(s) at line {where} are not authenticated import values",
            )
            continue
        members = []
        failed = None
        for node, receipt in receipted:
            member_site = arm_coordinate(node)
            try:
                graph = graph_for(receipt)
            except DependencyArtifactAuthenticationError as exc:
                failed = (
                    "partition-member-no-derived-contract",
                    f"{receipt.target_symbol}: dependency artifact authentication "
                    f"failed: {exc}",
                )
                break
            resolved = resolve_import_binding(receipt, graph=graph, session=session)
            if not isinstance(resolved, ResolvedPythonObjectV1):
                kind = getattr(resolved, "kind", None) or "no-derived-contract"
                failed = (f"partition-member-{kind}", receipt.target_symbol)
                break
            frame_result = resolve_source_visible_frame(
                resolved,
                graph=graph,
                dependency_graphs=graphs,
                session=session,
            )
            if not isinstance(frame_result, ManagerConstructionGapV1):
                # An in-population member has a real body. Folding N derived
                # protocols under one selection is its own law; keep this arm
                # loud under a name that says so.
                failed = (
                    "partition-member-derived-unfolded",
                    f"{receipt.target_symbol} resolves to an enrolled definition",
                )
                break
            if frame_result.kind != "call-target-off-population":
                failed = (
                    f"partition-member-{frame_result.kind}",
                    f"{receipt.target_symbol}: {frame_result.detail}",
                )
                break
            demand_cid = receipt.demand.get("cid", receipt.use["cid"])
            roster = opaque_source_call_roster_of(
                OpaqueSourceCallObligationV1(
                    member_site,
                    str(receipt.target_symbol),
                    demand_cid,
                    "call-target-off-population",
                )
            )
            context.opaque_source_call_obligations.setdefault(member_site, roster)
            members.append(mint_opaque_cited_context_manager_ref(roster=roster))
        if failed is not None:
            kind, detail = failed
            _install_derivation_gap(context, coordinate, first_receipt, kind, detail)
            continue
        context.source_derived_contract_refs[coordinate] = (
            mint_partitioned_opaque_cited_context_manager_ref(
                use_site=coordinate, members=tuple(members)
            )
        )




def _constructor_application_from_spread(call_sugar, reduce_ctx):
    """Project typed ``**`` actuals on a local constructor into one application.

    ``SpreadCallSugar`` has no ``.args``/``.keywords`` surface.  Its enrolled
    constructor frame already expands a constructed DictValue through
    ``bind_actuals``; the bound roster is the constructor application.
    """
    from sugar_lift_py_tests.callable_application import CallableApplication
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.outcome import Complete
    from sugar_source_tree.panic import SugarNotWritten

    outcome = call_sugar.desugar(reduce_ctx)
    value = getattr(outcome, "value", None)
    bound = getattr(value, "bound_source_actuals", None)
    if not isinstance(value, CallSiteValue) or bound is None:
        raise SugarNotWritten(
            owner="_populate_same_module_class_manager_uses.collect_application",
            blame=getattr(call_sugar, "site", None),
            observed=(
                type(outcome).__name__
                if value is None
                else type(value).__name__
            ),
            requested="a spread constructor application with bound actuals",
            fix="project typed ** actuals onto the constructor frame or keep the call loud",
        )
    frame = call_sugar.source_call_frame
    parameters = tuple(getattr(frame, "parameters", ()))
    kinds = tuple(getattr(frame, "parameter_kinds", ()))
    positional = []
    keyword_names = []
    keyword_values = []
    for index, actual in enumerate(bound.actuals):
        kind = kinds[index] if index < len(kinds) else "positional_or_keyword"
        name = parameters[index] if index < len(parameters) else None
        if kind in {"keyword_only"} and name:
            keyword_names.append(name)
            keyword_values.append(actual)
        elif kind in {"positional_only", "positional_or_keyword"} and not keyword_names:
            positional.append(actual)
        elif kind in {"positional_or_keyword", "keyword_only"} and name:
            keyword_names.append(name)
            keyword_values.append(actual)
        elif kind in {"vararg", "kwarg"}:
            continue
        else:
            positional.append(actual)
    return Complete(
        CallableApplication(
            tuple(positional + keyword_values),
            tuple(keyword_names),
            call_sugar.site,
            call_occurrence=getattr(call_sugar, "call_occurrence", None),
        )
    )


def _constructor_application_bindings(call, application, *, owner_cid: str, term_owner: str):
    """Seal constructor actuals so effect-boundary derivation can project them.

    ``_derive_effect_boundary`` matches the exit formula against
    ``behavior.formal_actual_values``. Same-module ClassDef uses previously
    left those empty, so an expects-raise ``__exit__`` collapsed to
    ``exit-may-halt`` even when the constructor actual was a builtin like
    ``ValueError``. Bindings must carry testimony of the same term CID
    ``ConstructedManagerBehaviorV1`` checks against those values.
    """
    from sugar_lift_py_tests.ir import _term_content_cid
    from sugar_source_tree.binding_provenance import (
        BindingCoordinateV1,
        ConstructedValueTestimonyV1,
    )
    from sugar_source_tree.binding_state import BindingEntryV1, BoundBindingStateV1
    from sugar_source_tree.panic import SugarNotWritten

    nodes = (*call.args, *(keyword.value for keyword in call.keywords))
    values = tuple(application.arguments)
    if len(nodes) != len(values):
        if any(getattr(keyword, "arg", None) is None for keyword in call.keywords):
            # Typed ``**`` expansion binds more formals than there are
            # syntactic nodes.  Seal each actual against the constructor call
            # fragment rather than inventing a source node per expanded key.
            bindings = []
            for index, value in enumerate(values):
                try:
                    term_cid = _term_content_cid(value.to_term(owner=term_owner))
                    testimony = ConstructedValueTestimonyV1.mint(call.fragment, term_cid)
                    coordinate = BindingCoordinateV1.mint(
                        owner_cid, call.fragment, ("constructor-actual", index)
                    )
                except (SugarNotWritten, TypeError, ValueError):
                    return None
                bindings.append(
                    BindingEntryV1(
                        coordinate=coordinate,
                        state=call,
                        sealed_state=BoundBindingStateV1(testimony),
                    )
                )
            return tuple(bindings)
        return None
    bindings = []
    for index, (node, value) in enumerate(zip(nodes, values, strict=True)):
        try:
            term_cid = _term_content_cid(value.to_term(owner=term_owner))
            testimony = ConstructedValueTestimonyV1.mint(node.fragment, term_cid)
            coordinate = BindingCoordinateV1.mint(
                owner_cid, node.fragment, ("constructor-actual", index)
            )
        except (SugarNotWritten, TypeError, ValueError):
            return None
        bindings.append(
            BindingEntryV1(
                coordinate=coordinate,
                state=node,
                sealed_state=BoundBindingStateV1(testimony),
            )
        )
    return tuple(bindings)



def _receiver_from_constructor_outcome(outcome):
    """Project constructor application to the completed manager receiver.

    ``ClassDefinitionValue.callable_application_with`` returns ``Complete``
    when the initializer folds to one path. Once the body keeps an unfolded
    branch or a validation halt (``if expected_exceptions == () ...: raise``),
    the same construction is an ``ExitSet``. ``Complete`` unwraps through
    ``.value``; ``ExitSet`` has no ``.value``, and reading it invented
    ``non-manager-result: NoneType`` after the receiver was already
    constructed. Validation Halted arms stay out of the manager the same way
    protocol construction already filters them.
    """
    from sugar_lift_py_tests.floor import ObjectValue, ReceiverStatePartitionValue
    from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet

    if isinstance(outcome, Complete):
        return outcome.value
    if isinstance(outcome, ExitSet):
        found = []
        for exit_ in outcome.exits:
            if not isinstance(exit_, Completed):
                continue
            value = exit_.value
            if isinstance(value, Complete):
                value = value.value
            if isinstance(value, (ObjectValue, ReceiverStatePartitionValue)):
                found.append(value)
        if len(found) == 1:
            return found[0]
        return None
    return getattr(outcome, "value", None)


def _populate_same_module_class_manager_uses(source_file, context, uses) -> None:
    """Derive CM contracts for same-module ClassDef call managers.

    Import receipts never fire for local constructors. When Call.func Name
    binds to exactly one module ClassDef, construct the instance via the
    ordinary Call floor (force_floor), then protocol + summary + native
    enter/exit publication — one pipeline with the import-backed door.
    """
    from sugar_lift_py_tests.context.reduce_context import ReduceContext
    from sugar_lift_py_tests.context_manager_resolution import (
        SourceDerivedContextManagerRefV1,
    )
    from sugar_lift_py_tests.floor import ObjectValue
    from sugar_lift_py_tests.callable_application import CallableApplication
    from sugar_lift_py_tests.floor import (
        ClassDefinitionValue,
        ReceiverStatePartitionValue,
    )
    from sugar_lift_py_tests.outcome import Complete
    from sugar_lift_py_tests.temporal import builtin_name_temporal
    from sugar_source_tree.nodes import Call, ClassDef, Name
    from sugar_source_tree.panic import SugarNotWritten

    from .canonical import cid_of_json
    from .manager_construction import (
        ConstructedManagerBehaviorV1,
        _floor_tuple_construct_fields,
    )
    from .manager_protocol_construction import (
        ConstructedManagerProtocolV1,
        _completed_object_receivers,
        construct_manager_protocol,
    )

    reduce_ctx = ReduceContext(temporal=builtin_name_temporal())

    def collect_application(call_sugar):
        """Collect authenticated call actuals without re-entering Call.sugar()."""
        from sugar_lift_py_tests.sugar.spread_sugar import SpreadCallSugar

        if isinstance(call_sugar, SpreadCallSugar):
            return _constructor_application_from_spread(call_sugar, reduce_ctx)

        if not (hasattr(call_sugar, "args") and hasattr(call_sugar, "keywords")):
            # A spread/starred manager call (``with LocalClass(*args): ...``)
            # constructs a SpreadCallSugar with no positional/keyword actual
            # surface.  Refuse as a COUNTABLE terminal (the caller installs a
            # local derivation gap) rather than crashing with a bare
            # AttributeError that voids the whole file as an instrument failure.
            raise SugarNotWritten(
                owner="_populate_same_module_class_manager_uses.collect_application",
                blame=getattr(call_sugar, "site", None),
                observed=(
                    f"{type(call_sugar).__name__} exposes no authenticated "
                    "positional/keyword actual surface"
                ),
                requested="a call sugar with authenticated args/keywords",
                fix="construct spread/starred manager-call actuals or keep the call loud",
            )

        def positional(index, values):
            if index == len(call_sugar.args):
                return keywords(0, values, ())
            return call_sugar.args[index].desugar(reduce_ctx).and_then(
                lambda value: value.project_operation_receiver_outcome(
                    reduce_ctx, owner="same-module ClassDef positional actual"
                ).and_then(
                    lambda actual: positional(index + 1, values + (actual,))
                )
            )

        def keywords(index, values, names):
            if index == len(call_sugar.keywords):
                return Complete(
                    CallableApplication(values, names, call_sugar.site,
                                        call_occurrence=call_sugar.call_occurrence)
                )
            name, argument = call_sugar.keywords[index]
            return argument.desugar(reduce_ctx).and_then(
                lambda value: value.project_operation_receiver_outcome(
                    reduce_ctx, owner="same-module ClassDef keyword actual"
                ).and_then(
                    lambda actual: keywords(
                        index + 1, values + (actual,), names + (name,)
                    )
                )
            )

        return positional(0, ())

    for _key, (coordinate, call, exit_face_id) in uses.items():
        if coordinate in context.source_derived_contract_refs:
            continue
        if not isinstance(call, Call) or not isinstance(call.func, Name):
            continue
        binds = (call.unit.module_direct_bindings or {}).get(call.func.id, ())
        if len(binds) != 1 or not isinstance(binds[0], ClassDef):
            continue
        class_def = binds[0]
        target_symbol = f"python:local:{class_def.name}"
        try:
            class_outcome = class_def.sugar().desugar(reduce_ctx)
            class_value = getattr(class_outcome, "value", None)
            if type(class_value) is not ClassDefinitionValue:
                _install_local_derivation_gap(
                    context,
                    coordinate,
                    target_symbol,
                    "class-definition-not-constructed",
                    type(class_outcome).__name__,
                )
                continue
            application = collect_application(call.sugar())
            application_value = getattr(application, "value", None)
            if application_value is None:
                _install_local_derivation_gap(
                    context, coordinate, target_symbol,
                    "call-arguments-not-constructed", type(application).__name__
                )
                continue
            result_outcome = class_value.callable_application_with(
                application_value, reduce_ctx
            )
            result = _receiver_from_constructor_outcome(result_outcome)
            if isinstance(result, ObjectValue):
                if getattr(result, "defining_class", None) is not class_value:
                    _install_local_derivation_gap(
                        context,
                        coordinate,
                        target_symbol,
                        "class-definition-provenance-mismatch",
                        "constructed receiver is not owned by authenticated class_def",
                    )
                    continue
            elif isinstance(result, ReceiverStatePartitionValue):
                leaves = _completed_object_receivers(result)
                if not leaves or any(
                    getattr(leaf, "defining_class", None) is not class_value
                    for leaf in leaves
                ):
                    _install_local_derivation_gap(
                        context,
                        coordinate,
                        target_symbol,
                        "class-definition-provenance-mismatch",
                        "constructed receiver is not owned by authenticated class_def",
                    )
                    continue
            else:
                _install_local_derivation_gap(
                    context,
                    coordinate,
                    target_symbol,
                    "non-manager-result",
                    type(result).__name__,
                )
                continue
        except (SugarNotWritten, TypeError) as exc:
            kind, detail = _populate_body_defect_kind_detail(exc)
            _install_local_derivation_gap(
                context, coordinate, target_symbol, kind, detail
            )
            continue
        result = _floor_tuple_construct_fields(
            result, tuple(application_value.arguments)
        )
        if isinstance(result, ObjectValue):
            receivers = (result,)
        elif isinstance(result, ReceiverStatePartitionValue):
            receivers = _completed_object_receivers(result)
        else:
            _install_local_derivation_gap(
                context,
                coordinate,
                target_symbol,
                "non-manager-result",
                type(result).__name__,
            )
            continue
        enter_method = next(
            (
                method
                for receiver in receivers
                for method in receiver.methods
                if method.name == "__enter__"
            ),
            None,
        )
        frame = (
            getattr(enter_method, "source_call_frame", None) if enter_method else None
        )
        frame_cid = getattr(frame, "frame_cid", None) or result.identity
        actual_values = tuple(application_value.arguments)
        bindings = _constructor_application_bindings(
            call,
            application_value,
            owner_cid=class_def.fragment.seal().cid,
            term_owner=target_symbol,
        )
        if bindings is None:
            actual_values = ()
            bindings = ()
        preimage = {
            "kind": "constructed-manager-behavior",
            "schemaVersion": "1",
            "resolvedObjectCid": target_symbol,
            "receiverStateCid": result.identity,
            "formalActualBindings": [item.wire() for item in bindings],
            "sourceCallFrameCid": frame_cid,
            "factoryPrefixCids": [],
        }
        behavior = ConstructedManagerBehaviorV1(
            resolved_object_cid=target_symbol,
            manager_construction_cid=cid_of_json(preimage),
            receiver_state=result,
            receiver_state_cid=result.identity,
            formal_actual_bindings=tuple(bindings),
            source_call_frame_cid=frame_cid,
            formal_actual_values=tuple(actual_values) if bindings else (),
            source_call_frame=frame,
            factory_prefix=(),
            factory_prefix_cids=(),
        )
        try:
            protocol = construct_manager_protocol(behavior, exit_face_id=exit_face_id)
        except (SugarNotWritten, TypeError) as exc:
            kind, detail = _populate_body_defect_kind_detail(exc)
            _install_local_derivation_gap(
                context, coordinate, target_symbol, kind, detail
            )
            continue
        if not isinstance(protocol, ConstructedManagerProtocolV1):
            if _publish_proven_non_manager_head(
                context,
                coordinate,
                call,
                class_def,
                protocol,
                construction_total=isinstance(result_outcome, Complete)
                and isinstance(result_outcome.value, ObjectValue),
            ):
                continue
            kind, detail = _gap_kind_and_detail(protocol)
            _install_local_derivation_gap(
                context, coordinate, target_symbol, kind, detail
            )
            continue
        summary = derive_manager_summary(protocol, behavior=behavior)
        if not isinstance(summary, DerivedManagerSummaryV1):
            kind, detail = _gap_kind_and_detail(summary)
            _install_local_derivation_gap(
                context, coordinate, target_symbol, kind, detail
            )
            continue
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


def _same_module_factory_return(function_def):
    """The one ``return <Call>`` a plain module factory leaves by, else None.

    The factory's whole body is imports plus that single trailing return, so
    the value ``with factory(...)`` enters is exactly the returned call's
    result, whatever path the call takes.
    """
    from sugar_source_tree.nodes import Call, Import, ImportFrom, Return

    body = tuple(function_def.body)
    if not body or not isinstance(body[-1], Return):
        return None
    if not all(
        isinstance(statement, (Import, ImportFrom))
        or statement.kind == "Expr"
        and statement.value.kind == "Constant"
        for statement in body[:-1]
    ):
        return None
    value = body[-1].value
    return value if isinstance(value, Call) else None


def _populate_same_module_factory_manager_uses(
    context,
    uses,
    value_receipts_by_site,
    *,
    graphs,
    session,
    distribution_index,
) -> None:
    """``with f(...)`` where ``f`` is this module's plain factory.

    ``pandas.io.common.urlopen`` is ``import urllib.request`` then ``return
    urllib.request.urlopen(*args, **kwargs)``: the manager the With enters is
    that vendor call's result.  The returned call's callee is followed through
    its authenticated import value receipt to the object the export door
    names.  When
    the callee is off the enrolled population (CPython's ``urllib.request``),
    the manager is cited, never materialized: the With keeps Python's law with
    enter, exit and suppression open and two-faced
    (``WithOpaqueCitedManagerSugar``), and the head still runs the factory's
    own body.  Any other return shape, or a callee the door does not cite,
    is left for ``With`` to refuse.
    """
    from sugar_lift_py_tests.context_manager_resolution import (
        OpaqueSourceCallObligationV1,
        OpaqueSourceCallRosterV1,
        mint_opaque_cited_context_manager_ref,
    )
    from sugar_source_tree.nodes import AsyncFunctionDef, Call, FunctionDef, Name

    from .dependency_artifact import (
        DependencyArtifactAuthenticationError,
        ResolvedPythonObjectV1,
        resolve_import_binding,
    )
    from .manager_construction import (
        _dependency_graph_for_top,
        _graph_is_off_population,
    )

    for _key, (coordinate, call, _exit_face_id) in uses.items():
        if coordinate in context.source_derived_contract_refs:
            continue
        if not isinstance(call, Call) or not isinstance(call.func, Name):
            continue
        binds = (call.unit.module_direct_bindings or {}).get(call.func.id, ())
        if len(binds) != 1 or type(binds[0]) is not FunctionDef:
            continue
        function_def = binds[0]
        if function_def.decorators or isinstance(function_def, AsyncFunctionDef):
            continue
        if any(node.kind in ("Yield", "YieldFrom") for node in function_def.walk()):
            continue
        returned = _same_module_factory_return(function_def)
        if returned is None:
            continue
        # The callee's identity does not depend on the operands, so it is
        # authenticated by the value-occurrence receipt at the callee
        # expression (``*args, **kwargs`` calls carry no call-target row).
        span = returned.func.line_col_span()
        receipt = value_receipts_by_site.get(
            (
                returned.unit.source_cid,
                span.start_line,
                span.start_col,
                span.end_line,
                span.end_col,
            )
        )
        if receipt is None:
            continue
        top_level = receipt.target_symbol.removeprefix("python:").split(".", 1)[0]
        try:
            graph = graphs.get(top_level) or _dependency_graph_for_top(
                top_level,
                session=session,
                dependency_graphs=graphs,
                distribution_index=distribution_index,
            )
        except DependencyArtifactAuthenticationError:
            continue
        resolved = resolve_import_binding(receipt, graph=graph, session=session)
        if not isinstance(resolved, ResolvedPythonObjectV1):
            continue
        if not _graph_is_off_population(
            graph, session=session, module_name=resolved.module_name
        ):
            continue
        roster = OpaqueSourceCallRosterV1(
            coordinate,
            receipt.target_symbol,
            "call-target-off-population",
            (
                OpaqueSourceCallObligationV1(
                    coordinate,
                    receipt.target_symbol,
                    resolved.cid,
                    resolution_kind="call-target-off-population",
                ),
            ),
        )
        context.source_derived_contract_refs[coordinate] = (
            mint_opaque_cited_context_manager_ref(roster=roster)
        )


def _populate_same_module_generator_manager_uses(
    context, uses, *, session, graphs, distribution_index
) -> None:
    """Derive ``with g(...)`` where ``g`` is a same-module decorated generator.

    Import receipts never fire for a local callee, so a module's own
    ``@contextlib.contextmanager`` generator was left ``runtime-selected``
    and its generator protocol was never applied. The law is the import
    road's, applied to the module binding: ``Call.func`` binds to exactly one
    module FunctionDef whose body is a generator and whose decorator resolves
    (through its authenticated import binding) to a function returning a
    helper that constructs one class with distinct ``__enter__``/``__exit__``
    -- contextlib's ``_GeneratorContextManager``, cited from the stdlib source.
    The frame is seated and published through the same generator-backed door,
    so the one ``generator_manager_exit`` law runs every body exit. When the
    decorator's protocol cannot be cited, the use is a named gap, never a
    seated frame: a local generator is not a manager on its spelling.
    """
    from sugar_source_tree.nodes import AsyncFunctionDef, Call, FunctionDef, Name
    from sugar_source_tree.panic import SugarNotWritten

    from .canonical import cid_of_json
    from .manager_construction import _install_source_call_frame

    for _key, (coordinate, call, exit_face_id) in uses.items():
        if coordinate in context.source_derived_contract_refs:
            continue
        if not isinstance(call, Call) or not isinstance(call.func, Name):
            continue
        binds = (call.unit.module_direct_bindings or {}).get(call.func.id, ())
        if len(binds) != 1 or not isinstance(binds[0], (FunctionDef, AsyncFunctionDef)):
            continue
        function_def = binds[0]
        if isinstance(function_def, AsyncFunctionDef) and function_def.decorators:
            # What a decorated ``async def`` returns is the decorator's to say;
            # no generator protocol is read from its spelling.  When the
            # decorator's source constructs one class whose MRO is proven to
            # lack ``__enter__``/``__exit__`` (``@asynccontextmanager``), the
            # With raises the interpreter's TypeError after the call.
            _publish_decorated_non_manager_head(
                context,
                coordinate,
                call,
                function_def,
                session=session,
                graphs=graphs,
                distribution_index=distribution_index,
            )
            continue
        target_symbol = f"python:local:{function_def.name}"
        try:
            frame, generator_target = _source_visible_frame_for_function(
                function_def
            )
        except (SugarNotWritten, TypeError):
            # No frame, no generator claim: the require door stays loud.
            continue
        if frame is None or frame.generator_steps is None:
            # Not a generator: another derivation (or the require door) owns it.
            continue
        if not getattr(function_def, "decorators", ()):
            # An undecorated generator function returns the generator object
            # itself, which has no ``__enter__``: seat the frame so the With
            # constructs the interpreter's own TypeError (#7595), never a
            # manager and never a runtime-selected gap.
            _install_source_call_frame(context, call, frame)
            context.source_manager_provider_calls[coordinate] = call
            continue
        declined: list[str] = []
        if (
            _protocol_coords_from_generator_decorators(
                generator_target,
                session=session,
                graph=None,
                dependency_graphs=graphs,
                distribution_index=distribution_index,
                declined=declined,
            )
            is None
        ):
            if _publish_decorated_non_manager_head(
                context,
                coordinate,
                call,
                function_def,
                session=session,
                graphs=graphs,
                distribution_index=distribution_index,
            ):
                continue
            _install_local_derivation_gap(
                context,
                coordinate,
                target_symbol,
                "generator-protocol",
                "native enter/exit definition coordinates unavailable"
                + (f" [{'; '.join(declined)}]" if declined else ""),
            )
            continue
        # Seat the frame in the form the installed-frame rewrite leaves it,
        # so the protocol's frame CID is the CID the provider call allocates.
        frame = _as_rewriting_generator_frame(
            _frame_with_nested_manager_steps(frame, ())
        )
        _install_source_call_frame(context, call, frame)
        context.source_manager_provider_calls[coordinate] = call
        try:
            _publish_generator_backed_resource_contract(
                context,
                coordinate,
                frame=frame,
                generator_target=generator_target,
                exit_face_id=exit_face_id,
                receipt=None,
                session=session,
                graph=None,
                dependency_graphs=graphs,
                distribution_index=distribution_index,
                resolved_cid=cid_of_json(
                    {
                        "kind": "same-module-generator-manager",
                        "schemaVersion": "1",
                        "definitionCid": function_def.fragment.seal().cid,
                    }
                ),
                local_target_symbol=target_symbol,
            )
        except (SugarNotWritten, TypeError) as exc:
            kind, detail = _populate_body_defect_kind_detail(exc)
            _install_local_derivation_gap(
                context, coordinate, target_symbol, kind, detail
            )


def _populate_builtin_c_manager_uses(context, uses) -> None:
    """Seat the C-manager law at ``with open(...)``.

    Import receipts never fire for a builtin name.  When the head calls a name
    the module binds nowhere, and that builtin is the C function its own
    interpreter-owned module exports (``builtins.open`` is ``_io.open``), the
    head is a two-faced C call and the ``with`` law runs over its opaque
    result exactly as for an imported C function (``decimal.localcontext``):
    enter and exit are two-faced slot calls and suppression is ``py.truthy`` of
    the opaque exit result.  Nothing is claimed about the result's type.
    """
    from sugar_source_tree.nodes import Call, Name

    from .language_owned_c_manager import mint_builtin_c_manager_ref

    for _key, (coordinate, call, _exit_face_id) in uses.items():
        if coordinate in context.source_derived_contract_refs:
            continue
        if not isinstance(call, Call) or not isinstance(call.func, Name):
            continue
        owned = mint_builtin_c_manager_ref(coordinate, call.func.id, call.unit.source)
        if owned is not None:
            context.source_derived_contract_refs[coordinate] = owned


def _populate_formal_selected_manager_uses(
    source_file, context, *, selected_coordinates=None
) -> None:
    """Seat the opaque two-faced manager at ``with p.m():`` / ``with self.x:``.

    Nothing in the frame knows the type of the object a parameter holds, so no
    derivation can name its ``__enter__``/``__exit__``.  When the head only
    reads that parameter through attribute reads and constant-argument calls,
    the manager is opaque and keyed on the With's site: construction, enter
    and exit are two-faced and suppression is the undecided truth of the
    exit result.
    """
    from sugar_lift_py_tests.context_manager_resolution import (
        SourceFragmentCoordinateV1,
    )
    from sugar_source_tree.formal_manager_head import formal_manager_head
    from sugar_source_tree.nodes import With

    from .formal_selected_manager import mint_formal_selected_manager_ref

    source = source_file.root.unit.source
    for node in source_file.root.walk():
        if not isinstance(node, With):
            continue
        for item in node.items:
            expr = item.context_expr
            coordinate = SourceFragmentCoordinateV1(
                expr.unit.source_cid, *item._manager_use_site_span()
            )
            if coordinate in context.source_derived_contract_refs:
                continue
            if selected_coordinates is not None and coordinate not in selected_coordinates:
                continue
            start_line, start_col, _end_line, _end_col = item._manager_use_site_span()
            head = formal_manager_head(source, start_line, start_col)
            if head is None:
                continue
            context.source_derived_contract_refs[coordinate] = (
                mint_formal_selected_manager_ref(coordinate, head)
            )


def _populate_runtime_selected_head_uses(
    source_file, context, *, selected_coordinates=None
) -> None:
    """Cite the manager at a head whose value a run-time string selects.

    ``klass = getattr(module, klass)`` then ``with klass(path) as f:``: which
    class stands at the head is chosen by a string at run time, so there is no
    callee for any derivation to read.  The With is constructed over the
    existing opaque citation (enter, exit and suppression open and two-faced;
    the head itself still evaluates through its own sugar).  The citation names
    no callee -- it has none -- only the head's own coordinate and the reason
    kind ``head-runtime-selected``.  Runs after every reader, so a head any
    reader seated (a construction or its gap) is never cited over.
    """
    from sugar_lift_py_tests.context_manager_resolution import (
        OpaqueSourceCallObligationV1,
        SourceFragmentCoordinateV1,
        _hash_json,
        mint_opaque_cited_context_manager_ref,
        opaque_source_call_roster_of,
    )
    from sugar_source_tree.formal_manager_head import runtime_selected_manager_head
    from sugar_source_tree.nodes import With

    source = source_file.root.unit.source
    for node in source_file.root.walk():
        if not isinstance(node, With):
            continue
        for item in node.items:
            coordinate = SourceFragmentCoordinateV1(
                item.context_expr.unit.source_cid, *item._manager_use_site_span()
            )
            if coordinate in context.source_derived_contract_refs:
                continue
            if coordinate in context.opaque_source_call_obligations:
                continue
            if selected_coordinates is not None and coordinate not in selected_coordinates:
                continue
            start_line, start_col, _end_line, _end_col = item._manager_use_site_span()
            if runtime_selected_manager_head(source, start_line, start_col) is None:
                continue
            owner_cid = _hash_json(
                {
                    "kind": "runtime-selected-head-demand",
                    "useSite": coordinate.wire(),
                }
            )
            roster = opaque_source_call_roster_of(
                OpaqueSourceCallObligationV1(
                    coordinate, "", owner_cid, "head-runtime-selected"
                )
            )
            context.source_derived_contract_refs[coordinate] = (
                mint_opaque_cited_context_manager_ref(roster=roster)
            )


def _publish_proven_non_manager_head(
    context, coordinate, call, class_def, gap, *, construction_total: bool
):
    """Seat a source absence proof for ``with C(...)`` when the protocol gap
    (``enter-missing`` / ``exit-missing``) agrees with the class's source MRO.

    Only a construction that completes on one path is admitted: the With
    evaluates the head as an ordinary call, and a constructor that may raise
    must keep its own faces, which that call does not yet carry.
    """
    if not construction_total:
        return False
    from .manager_protocol_absence import prove_manager_protocol_absence

    kind = getattr(gap, "kind", None)
    if kind not in ("enter-missing", "exit-missing"):
        return False
    proof = prove_manager_protocol_absence(class_def)
    if proof is None:
        return False
    if kind == "enter-missing" and proof.has_enter:
        return False
    if kind == "exit-missing" and (not proof.has_enter or proof.has_exit):
        return False
    context.source_non_manager_heads[coordinate] = proof
    return True


def _publish_decorated_non_manager_head(
    context, coordinate, call, function_def, *, session, graphs, distribution_index
) -> bool:
    """``with g(...)`` for ``@d async def g``: seat ``g``'s frame and the proof
    that ``d``'s constructed class lacks the sync protocol."""
    from sugar_source_tree.panic import SugarNotWritten

    from .manager_construction import _install_source_call_frame
    from .manager_protocol_absence import prove_decorated_manager_absence

    if len(function_def.decorators) != 1:
        return False
    outcome = _construct_decorator_function(
        function_def.decorators[0],
        session=session,
        graph=None,
        dependency_graphs=graphs,
        distribution_index=distribution_index,
    )
    if not isinstance(outcome, DecoratorConstructedV1):
        return False
    proof = prove_decorated_manager_absence(function_def, outcome.function)
    if proof is None:
        return False
    try:
        frame, _generator_target = _source_visible_frame_for_function(function_def)
    except (SugarNotWritten, TypeError):
        return False
    if frame is None or frame.generator_steps is None:
        return False
    # ``helper(*args, **kwds)`` constructs the class, whose ``__init__`` calls
    # ``func(*args, **kwds)``: the call's argument binding is g's own frame.
    _install_source_call_frame(context, call, frame)
    context.source_manager_provider_calls[coordinate] = call
    context.source_non_manager_heads[coordinate] = proof
    return True


def _install_local_derivation_gap(
    context, coordinate, target_symbol: str, kind: str, detail: str | None = None
) -> None:
    """Gap row for a same-module manager use (no import receipt)."""
    from sugar_lift_py_tests.context_manager_resolution import (
        ContextManagerResolutionGapV1,
        _hash_json,
    )

    demand_cid = _hash_json(
        {
            "kind": "local-manager-demand",
            "useSite": {
                "sourceCid": coordinate.source_cid,
                "startLine": coordinate.start_line,
                "startCol": coordinate.start_col,
                "endLine": coordinate.end_line,
                "endCol": coordinate.end_col,
            },
            "targetSymbol": target_symbol,
        }
    )
    if _seat_off_population_citation(
        context, coordinate, target_symbol, kind, demand_cid
    ):
        return
    gap = ContextManagerResolutionGapV1(
        demand_cid,
        coordinate,
        target_symbol,
        kind,
        (),
        detail,
    )
    context.source_derived_contract_refs[coordinate] = gap


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


def _publish_manager_face_partition(
    context,
    coordinate,
    behavior,
    *,
    receipt,
    exit_face_id,
    session,
    graph,
    dependency_graphs,
    distribution_index,
    positional_sugars,
    keyword_sugars,
) -> None:
    """Publish one resource ref whose protocol enters each face's own manager.

    A factory returning ``nullcontext()`` under one guard and
    ``assert_produces_warning(...)`` under its complement returns a class
    manager on one face and a generator manager on the other.  Each is
    constructed here by the door its kind already has: the class manager's
    ``__enter__``/``__exit__`` frames, the generator's decorator-constructed
    lifecycle.  The With enters every manager face its reduction of the
    factory produces, under that face's guard, and unions the exits.  Never
    one face for all.  A face whose manager cannot be constructed keeps its
    named refusal.
    """
    from sugar_lift_py_tests.context_manager_contract import (
        EnterResultContractV1,
        ExitContractV1,
        ImportSignatureV2,
        ProtocolResourceSemanticsV1,
        ReturnTruthinessDispositionV1,
    )
    from sugar_lift_py_tests.context_manager_resolution import (
        SourceCallActualSugarsV1,
        SourceDerivedContextManagerRefV1,
    )
    from sugar_lift_py_tests.ir import PrimitiveSort
    from sugar_source_tree.panic import SugarNotWritten

    from .manager_protocol_construction import (
        ConstructedManagerProtocolV1,
        construct_generator_backed_protocol,
        construct_manager_partition_protocol,
        construct_manager_protocol,
    )

    def refuse(kind, detail=None):
        _install_derivation_gap_for_receipt(context, coordinate, receipt, kind, detail)

    class_protocol = None
    if behavior.class_behavior is not None:
        try:
            class_protocol = construct_manager_protocol(
                behavior.class_behavior, exit_face_id=exit_face_id
            )
        except (SugarNotWritten, TypeError) as exc:
            refuse(*_populate_body_defect_kind_detail(exc))
            return
        if not isinstance(class_protocol, ConstructedManagerProtocolV1):
            refuse(*_gap_kind_and_detail(class_protocol))
            return
    generator_protocols = []
    for machine in behavior.generators:
        # The frame that allocated this face's machine: the protocol enters
        # exactly the machines that frame allocates.
        frame = machine.source_frame
        declined: list[str] = []
        coords = _protocol_coords_from_generator_decorators(
            frame.owner,
            session=session,
            graph=graph,
            dependency_graphs=dependency_graphs,
            distribution_index=distribution_index,
            declined=declined,
        )
        if coords is None:
            refuse(
                "generator-protocol",
                "native enter/exit definition coordinates unavailable"
                + (f" [{'; '.join(declined)}]" if declined else ""),
            )
            return
        enter, exit_ = coords
        protocol = construct_generator_backed_protocol(
            frame=frame,
            enter_definition=enter,
            exit_definition=exit_,
            exit_face_id=exit_face_id,
            construction_cid=behavior.manager_construction_cid,
        )
        gap = _generator_protocol_construction_gap(protocol)
        if gap is not None:
            refuse(*_gap_kind_and_detail(gap))
            return
        generator_protocols.append(protocol)
    protocol = construct_manager_partition_protocol(
        manager_construction_cid=behavior.manager_construction_cid,
        exit_face_id=exit_face_id,
        class_protocol=class_protocol,
        generator_protocols=tuple(generator_protocols),
    )
    # Each member's exit result decides suppression for its own faces: a
    # generator's GCM throw/resume result, a class manager's returned value.
    semantics = ProtocolResourceSemanticsV1(
        EnterResultContractV1(PrimitiveSort("Value")),
        ExitContractV1(ReturnTruthinessDispositionV1()),
    )
    summary_cid = cid_of_json(
        {
            "kind": "source-derived-manager-partition-summary",
            "schemaVersion": "1",
            "protocolConstructionCid": protocol.protocol_construction_cid,
        }
    )
    context.source_derived_contract_refs[coordinate] = (
        SourceDerivedContextManagerRefV1(
            coordinate,
            summary_cid,
            semantics,
            ImportSignatureV2(()),
            protocol,
            call_actual_sugars=SourceCallActualSugarsV1(
                coordinate,
                positional_sugars,
                keyword_sugars,
                behavior.source_call_frame,
            ),
        )
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
    local_target_symbol: str | None = None,
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

    def _install_derivation_gap(context, receiver, receipt, kind, detail=None):
        # A same-module manager has no import receipt: its demand is local.
        if receipt is None:
            _install_local_derivation_gap(
                context, receiver, local_target_symbol, kind, detail
            )
            return
        _install_derivation_gap_for_receipt(context, receiver, receipt, kind, detail)

    declined: list[str] = []
    coords = _protocol_coords_from_generator_decorators(
        generator_target,
        session=session,
        graph=graph,
        dependency_graphs=dependency_graphs,
        distribution_index=distribution_index,
        declined=declined,
    )
    if coords is None:
        # Name WHY, per decorator. "unavailable" was true of an off-population
        # citation, a missing binding and a malformed decorator body alike, so
        # the row could not say which one a reader was looking at.
        _install_derivation_gap(
            context,
            receiver,
            receipt,
            "generator-protocol",
            "native enter/exit definition coordinates unavailable"
            + (f" [{'; '.join(declined)}]" if declined else ""),
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
                    if (
                        _generator_protocol_construction_gap(nested_protocol)
                        is not None
                    ):
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
    from sugar_source_tree.nodes import AsyncFunctionDef, FunctionDef

    if not isinstance(function_def, (FunctionDef, AsyncFunctionDef)):
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
        outcome = _construct_decorator_function(
            func,
            session=session,
            graph=graph,
            distribution_index=distribution_index,
        )
        if isinstance(outcome, DecoratorConstructedV1) and isinstance(
            outcome.function, FunctionDef
        ):
            return outcome.function
    return None


def _finally_term_step_for_nested_with(finalbody):
    """Name a handler-free finally suite as term payloads, or None.

    ``pass`` is skipped. Structured cleanup (assign, for, raise, a yield)
    stays unnameable here so ``name_body`` can seat it as cleanup_steps, or
    the containing With stays loud.
    """
    from sugar_lift_py_tests.generator_construction import FinallyStepV1
    from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
    from sugar_source_tree.nodes import Assert, Expr, For, Import, ImportFrom, Pass, Raise, While, Yield, YieldFrom
    from sugar_source_tree.panic import SugarNotWritten

    terms = []
    for item in finalbody:
        if isinstance(item, Pass):
            continue
        if isinstance(item, (Assert, For, Import, ImportFrom, Raise, While)):
            return None
        if isinstance(item, Expr) and isinstance(item.value, (Yield, YieldFrom)):
            return None
        if isinstance(item, Expr):
            try:
                value_sugar = item.value.sugar()
            except SugarNotWritten:
                return None
            if isinstance(value_sugar, ConstructedTermSugar):
                terms.append(value_sugar)
                continue
            return None
        try:
            sugar = item.sugar()
        except SugarNotWritten:
            return None
        if isinstance(sugar, ConstructedTermSugar):
            terms.append(sugar)
            continue
        return None
    return FinallyStepV1(tuple(terms))


def _compose_finally_for_nested_with(body_steps, cleanup_step):
    """Seat cleanup before every terminal face and on fall-through."""
    from sugar_lift_py_tests.generator_construction import (
        IfStepV1,
        RaiseStepV1,
        ReturnStepV1,
    )

    def compose_exits(branch):
        composed = []
        for step in branch:
            if isinstance(step, IfStepV1):
                step = IfStepV1(
                    step.guard,
                    compose_exits(step.then_steps),
                    compose_exits(step.else_steps),
                    step.fragment_cid,
                )
            if isinstance(step, (ReturnStepV1, RaiseStepV1)):
                composed.append(cleanup_step)
            composed.append(step)
        return tuple(composed)

    composed = []
    for step in body_steps:
        if isinstance(step, IfStepV1):
            step = IfStepV1(
                step.guard,
                compose_exits(step.then_steps),
                compose_exits(step.else_steps),
                step.fragment_cid,
            )
        if isinstance(step, (ReturnStepV1, RaiseStepV1)):
            composed.append(cleanup_step)
        composed.append(step)
    composed.append(cleanup_step)
    return tuple(composed)


def _nameable_nested_with_body_steps(body, *, scope=None) -> tuple | None:
    """Name With-body steps under the merged pre-yield law (Assign/If/Yield peers).

    A handler-free try/finally whose cleanup is term-only (or ``pass``) composes
    as body steps plus FinallyStepV1, the same seating as a top-level generator.
    A bare expression whose value is ConstructedTermSugar is TermStepV1, including
    ``warnings.simplefilter(...)``; the term is not invented as a performed filter.
    A ``for`` without ``orelse`` or an owned yield, whose target is a bare
    name, a tuple, or a list, is ForStepV1, using the same target-coordinate
    minting as a top-level generator. A bare name binds the iterated item;
    a tuple or list target still unpacks through iter/next and authenticated
    StopIteration. A ``while`` without ``orelse`` or an owned yield, whose
    guard is a constructed term and whose body is nameable, is WhileStepV1,
    the same step the top-level generator namer already seats. A false guard
    skips the body and continues; an undecided guard stays a typed gap.
    A ``raise`` that does not own a yield is RaiseStepV1, the same step a
    top-level generator already names; transition desugars the RaiseSugar
    and halts with the effect. An ``assert`` that does not own a yield is
    AssertStepV1, the same step a top-level generator names; ``assert True``
    advances and continues. An ``import`` that does not own a yield is
    ImportStepV1, the same step a top-level generator names; ``import math``
    advances and continues. A ``from ... import ...`` that does not own a
    yield is ImportFromStepV1, the same step a top-level generator names;
    ``from math import sqrt`` advances and continues. An attribute
    assignment ``holder.hidden = True`` is AttributeAssignStepV1, the same
    step a top-level generator already names. A ``yield from`` whose
    iterable is a constructed term is YieldFromStepV1, the same step a
    top-level generator already names; ``yield from (1,)`` delegates the
    item through already-written iter/next. A nested cited-opaque With
    is NestedCitedOpaqueManagerStepV1, the same step this namer already
    seats at the generator top level. This does not invent
    items, warning testimony, a bound on ``while True``, a loaded module,
    that the attribute was stored, or that a cleanup raise was suppressed.
    Returns None when any statement is unnameable — keeps the nested With loud.
    """
    from sugar_lift_py_tests.generator_construction import (
        AssignStepV1,
        AssertStepV1,
        AttributeAssignStepV1,
        ForStepV1,
        IfStepV1,
        ImportFromStepV1,
        ImportStepV1,
        InertStepV1,
        RaiseStepV1,
        ReturnStepV1,
        WhileStepV1,
        YieldFromStepV1,
        YieldStepV1,
    )
    from sugar_source_tree.nodes import (
        AnnAssign,
        Assert,
        Assign,
        Attribute,
        Constant,
        Expr,
        For,
        FunctionDef,
        If,
        Import,
        ImportFrom,
        List,
        Name,
        Tuple_,
        Pass,
        Raise,
        Return,
        Try,
        While,
        With,
        Yield,
        YieldFrom,
        generator_for_module_cid,
        generator_for_target_coordinates,
    )

    def name_one(statement):
        if isinstance(statement, Expr) and isinstance(statement.value, Yield):
            value = statement.value.value
            return YieldStepV1(None if value is None else value.sugar())
        if isinstance(statement, Expr) and isinstance(statement.value, YieldFrom):
            from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
            from sugar_source_tree.panic import SugarNotWritten

            occurrence = statement.value.fragment
            try:
                iterable = statement.value.value.sugar()
            except SugarNotWritten:
                return None
            if not isinstance(iterable, ConstructedTermSugar):
                return None
            return YieldFromStepV1(iterable, occurrence, occurrence.seal().cid)
        if isinstance(statement, Return):
            return ReturnStepV1(
                None if statement.value is None else statement.value.sugar()
            )
        if isinstance(statement, Raise) and not FunctionDef._owns_yield((statement,)):
            from sugar_lift_py_tests.sugar.raise_sugar import RaiseSugar
            from sugar_source_tree.panic import SugarNotWritten

            try:
                raise_sugar = statement.sugar()
            except SugarNotWritten:
                return None
            if not isinstance(raise_sugar, RaiseSugar):
                return None
            return RaiseStepV1(raise_sugar, statement.fragment.seal().cid)
        if isinstance(statement, Assert) and not FunctionDef._owns_yield((statement,)):
            from sugar_lift_py_tests.context_manager_resolution import (
                SourceFragmentCoordinateV1,
            )
            from sugar_source_tree.panic import SugarNotWritten

            try:
                assert_sugar = statement.sugar()
            except SugarNotWritten:
                return None
            span = statement.line_col_span()
            return AssertStepV1(
                assert_sugar=assert_sugar,
                assert_cid=statement.fragment.seal().cid,
                assert_coordinate=SourceFragmentCoordinateV1(
                    statement.unit.source_cid,
                    span.start_line,
                    span.start_col,
                    span.end_line,
                    span.end_col,
                ),
                occurrence=statement.fragment,
            )
        if isinstance(statement, Import) and not FunctionDef._owns_yield((statement,)):
            from sugar_lift_py_tests.context_manager_resolution import (
                SourceFragmentCoordinateV1,
            )
            from sugar_source_tree.panic import SugarNotWritten

            try:
                import_sugar = statement.sugar()
            except SugarNotWritten:
                return None
            span = statement.line_col_span()
            return ImportStepV1(
                import_sugar=import_sugar,
                coordinate=SourceFragmentCoordinateV1(
                    statement.unit.source_cid,
                    span.start_line,
                    span.start_col,
                    span.end_line,
                    span.end_col,
                ),
                occurrence=statement.fragment,
            )
        if isinstance(statement, ImportFrom) and not FunctionDef._owns_yield((statement,)):
            from sugar_lift_py_tests.context_manager_resolution import (
                SourceFragmentCoordinateV1,
            )
            from sugar_source_tree.panic import SugarNotWritten

            try:
                import_sugar = statement.sugar()
            except SugarNotWritten:
                return None
            span = statement.line_col_span()
            return ImportFromStepV1(
                import_sugar=import_sugar,
                coordinate=SourceFragmentCoordinateV1(
                    statement.unit.source_cid,
                    span.start_line,
                    span.start_col,
                    span.end_line,
                    span.end_col,
                ),
                occurrence=statement.fragment,
            )
        if isinstance(statement, Expr) and isinstance(statement.value, Constant):
            return InertStepV1(statement.kind)
        if (
            isinstance(statement, Expr)
            and not isinstance(statement.value, (Yield, YieldFrom))
        ):
            from sugar_lift_py_tests.generator_construction import TermStepV1
            from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
            from sugar_source_tree.panic import SugarNotWritten

            try:
                value_sugar = statement.value.sugar()
            except SugarNotWritten:
                return None
            if isinstance(value_sugar, ConstructedTermSugar):
                return TermStepV1(value_sugar, statement.fragment.seal().cid)
            return None
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
            isinstance(statement, Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], Attribute)
            and not FunctionDef._owns_yield((statement,))
        ):
            from sugar_source_tree.panic import SugarNotWritten

            target = statement.targets[0]
            try:
                receiver = target.value.sugar()
                value = statement.value.sugar()
            except SugarNotWritten:
                return None
            return AttributeAssignStepV1(
                receiver=receiver,
                attr=target.attr,
                value=value,
                fragment_cid=statement.fragment.seal().cid,
                target_cid=target.fragment.seal().cid,
                occurrence=target.fragment,
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
        if (
            isinstance(statement, For)
            and not statement.orelse
            and not FunctionDef._owns_yield((statement,))
            and isinstance(statement.target, (Name, Tuple_, List))
        ):
            from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
            from sugar_source_tree.panic import SugarNotWritten

            body_steps = name_body(statement.body)
            target_coordinates = generator_for_target_coordinates(statement)
            try:
                iterable = statement.iter.sugar()
            except SugarNotWritten:
                return None
            if (
                body_steps is None
                or target_coordinates is None
                or not isinstance(iterable, ConstructedTermSugar)
            ):
                return None
            return ForStepV1(
                iterable=iterable,
                target_coordinates=target_coordinates,
                body_steps=body_steps,
                module_cid=generator_for_module_cid(statement),
                fragment_cid=statement.fragment.seal().cid,
                occurrence=statement.fragment,
            )
        if (
            isinstance(statement, While)
            and not statement.orelse
            and not FunctionDef._owns_yield((statement,))
        ):
            from sugar_lift_py_tests.context_manager_resolution import (
                SourceFragmentCoordinateV1,
            )
            from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
            from sugar_source_tree.panic import SugarNotWritten

            body_steps = name_body(statement.body)
            try:
                guard = statement.test.sugar()
            except SugarNotWritten:
                return None
            if body_steps is None or not isinstance(guard, ConstructedTermSugar):
                return None
            span = statement.line_col_span()
            return WhileStepV1(
                guard=guard,
                body_steps=body_steps,
                fragment_cid=statement.fragment.seal().cid,
                coordinate=SourceFragmentCoordinateV1(
                    statement.unit.source_cid,
                    span.start_line,
                    span.start_col,
                    span.end_line,
                    span.end_col,
                ),
                occurrence=statement.fragment,
            )
        if isinstance(statement, With):
            return _cited_opaque_nested_step_for(statement, scope=scope)
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
        if (
            isinstance(statement, Try)
            and not statement.handlers
            and not statement.orelse
            and statement.finalbody
        ):
            body_steps = name_body(statement.body)
            from sugar_lift_py_tests.generator_construction import FinallyStepV1

            finalbody = tuple(
                item
                for item in statement.finalbody
                if not isinstance(item, Pass)
            )
            cleanup_steps = name_body(finalbody)
            if cleanup_steps is not None:
                # Term-only calls and structured cleanup share the sub-machine.
                # The statements path can complete a CallSiteValue without
                # reducing a source-visible body. ``pass`` is skipped so a
                # pass-only finally stays empty cleanup, not an Inert step.
                cleanup = FinallyStepV1((), cleanup_steps=cleanup_steps)
            else:
                cleanup = _finally_term_step_for_nested_with(statement.finalbody)
            if body_steps is None or cleanup is None:
                return None
            return _compose_finally_for_nested_with(body_steps, cleanup)
        return None

    def name_body(stmts):
        out = []
        for s in stmts:
            named = name_one(s)
            if named is None:
                return None
            if isinstance(named, tuple):
                out.extend(named)
            else:
                out.append(named)
        return tuple(out)

    return name_body(body)


def _generator_substitution_scope(frame) -> dict:
    """The same formal scope used to emit this frame's generator steps.

    After bind, that is the runtime BindingEntryV1 roster. Before bind, it is
    the unspecialized BindingCoordinateRef for each formal. Does not invent
    actuals or a default.
    """
    owner = getattr(frame, "owner", None)
    parameters = tuple(getattr(frame, "parameters", ()) or ())
    entries = tuple(getattr(frame, "runtime_entries", ()) or ())
    if owner is not None and entries and len(entries) == len(parameters):
        return dict(zip(parameters, entries, strict=True))
    coordinates = tuple(getattr(frame, "formal_coordinates", ()) or ())
    params = tuple(getattr(owner, "params", ()) or ()) if owner is not None else ()
    if (
        owner is not None
        and coordinates
        and len(coordinates) == len(params) == len(parameters)
    ):
        return {
            param.name: owner._make_coordinate_ref(param, coordinate)
            for param, coordinate in zip(params, coordinates, strict=True)
        }
    return {}


def _cite_formals_in_if_guards(statements, scope):
    """Rewrite ``if`` tests to cite bound formals, leaving ``for`` nodes intact.

    Full body substitution would run For.substitute and can replace a
    symbolic for with LoopRecurrenceStatement, which this namer does not
    seat. Only If tests are substituted; nested Ifs inside try/for bodies
    are rewritten the same way. Does not invent a default actual.
    """
    from sugar_source_tree.nodes import For, If, Try, While
    from sugar_source_tree.shadow import rewrite

    if not scope or not statements:
        return statements

    def rewrite_stmts(stmts):
        if not stmts:
            return stmts
        out = []
        changed = False
        for stmt in stmts:
            new = rewrite_stmt(stmt)
            out.append(new)
            if new is not stmt:
                changed = True
        return tuple(out) if changed else stmts

    def rewrite_stmt(stmt):
        if isinstance(stmt, If):
            new_test = stmt.test.substitute(scope)
            body = rewrite_stmts(stmt.body)
            orelse = rewrite_stmts(stmt.orelse)
            changes = {}
            if new_test is not stmt.test:
                changes["test"] = new_test
            if body is not stmt.body:
                changes["body"] = body
            if orelse is not stmt.orelse:
                changes["orelse"] = orelse
            return rewrite(stmt, **changes) if changes else stmt
        if isinstance(stmt, Try):
            changes = {}
            body = rewrite_stmts(stmt.body)
            finalbody = rewrite_stmts(stmt.finalbody)
            orelse = rewrite_stmts(stmt.orelse)
            if body is not stmt.body:
                changes["body"] = body
            if finalbody is not stmt.finalbody:
                changes["finalbody"] = finalbody
            if orelse is not stmt.orelse:
                changes["orelse"] = orelse
            if stmt.handlers:
                new_handlers = []
                handlers_changed = False
                for handler in stmt.handlers:
                    handler_body = rewrite_stmts(handler.body)
                    if handler_body is handler.body:
                        new_handlers.append(handler)
                    else:
                        handlers_changed = True
                        new_handlers.append(rewrite(handler, body=handler_body))
                if handlers_changed:
                    changes["handlers"] = tuple(new_handlers)
            return rewrite(stmt, **changes) if changes else stmt
        if isinstance(stmt, (For, While)):
            changes = {}
            body = rewrite_stmts(stmt.body)
            orelse = rewrite_stmts(stmt.orelse)
            if body is not stmt.body:
                changes["body"] = body
            if orelse is not stmt.orelse:
                changes["orelse"] = orelse
            return rewrite(stmt, **changes) if changes else stmt
        return stmt

    return rewrite_stmts(statements)


def _cited_opaque_nested_step_for(statement, *, scope=None):
    """Name a top-level cited-opaque With as a generator step, or None.

    Cites formals in ``if`` guards through the frame's formal scope, so an
    ``if expected_warning:`` is the bound formal rather than a free NameSugar.
    Does not run For.substitute, which would rewrite a symbolic for into a
    loop-recurrence the namer cannot seat. Leaves the With opaque when the
    body is unnameable, the as-target is not a simple Name, or the manager
    expression is not a constructed term. Does not invent enter or exit
    testimony, a decided guard, or a default actual.
    """
    from sugar_lift_py_tests.context_manager_resolution import (
        OpaqueCitedContextManagerRefV1,
        PartitionedOpaqueCitedContextManagerRefV1,
    )
    from sugar_lift_py_tests.generator_construction import NestedCitedOpaqueManagerStepV1
    from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
    from sugar_source_tree.nodes import Name
    from sugar_source_tree.panic import SugarNotWritten

    if len(statement.items) != 1:
        return None
    item = statement.items[0]
    ref = statement._prebound_manager_resolution(item)
    if type(ref) not in (
        OpaqueCitedContextManagerRefV1,
        PartitionedOpaqueCitedContextManagerRefV1,
    ):
        return None
    body = statement.body
    if scope:
        body = _cite_formals_in_if_guards(statement.body, scope)
    body_steps = _nameable_nested_with_body_steps(body, scope=scope)
    if body_steps is None:
        return None
    try:
        manager_sugar = item.context_expr.sugar()
    except SugarNotWritten:
        return None
    if not isinstance(manager_sugar, ConstructedTermSugar):
        return None
    optional = item.optional_vars
    if optional is not None and not isinstance(optional, Name):
        return None
    fragment_cid = statement.fragment.seal().cid
    occurrence_cid = item.context_expr.fragment.seal().cid
    return NestedCitedOpaqueManagerStepV1(
        manager=manager_sugar,
        contract_ref=ref,
        body_steps=body_steps,
        fragment_cid=fragment_cid,
        occurrence_cid=occurrence_cid,
        site=statement.fragment,
        as_name=None if optional is None else optional.id,
    )


def _frame_with_nested_manager_steps(frame, nested_layers: tuple):
    """Rewrite Opaque With steps when a nested layer or cited-opaque With resolves.

    Producer-owned: does not edit nodes.py emission. Leaves the frame unchanged
    when there is nothing to rewrite.
    """
    from types import SimpleNamespace

    from sugar_lift_py_tests.generator_construction import (
        NestedManagerStepV1,
        OpaqueStepV1,
    )
    from sugar_source_tree.nodes import With

    steps = getattr(frame, "generator_steps", None)
    if not steps:
        return frame
    owner = getattr(frame, "owner", None)
    with_stmts = [stmt for stmt in getattr(owner, "body", ()) or () if isinstance(stmt, With)]
    cited_by_cid = {}
    for stmt in with_stmts:
        named = _cited_opaque_nested_step_for(
            stmt, scope=_generator_substitution_scope(frame)
        )
        if named is not None:
            cited_by_cid[stmt.fragment.seal().cid] = named
    src_by_cid = {}
    src_order = []
    for layer in nested_layers:
        occurrence = getattr(layer, "occurrence", None) or {}
        with_cid = occurrence.get("withCid") if isinstance(occurrence, dict) else None
        if with_cid:
            src_by_cid[with_cid] = layer
        src_order.append(layer)
    if not cited_by_cid and not nested_layers:
        return frame
    rewritten = []
    src_idx = 0
    with_idx = 0
    rewrote = False
    for step in steps:
        if not (isinstance(step, OpaqueStepV1) and step.observed == "With"):
            rewritten.append(step)
            continue
        stmt = with_stmts[with_idx] if with_idx < len(with_stmts) else None
        with_idx += 1
        cid = stmt.fragment.seal().cid if stmt is not None else None
        cited = cited_by_cid.get(cid)
        if cited is not None:
            rewritten.append(cited)
            rewrote = True
            continue
        layer = src_by_cid.get(cid)
        if layer is None and cid not in src_by_cid and src_idx < len(src_order):
            layer = src_order[src_idx]
            src_idx += 1
        elif layer is not None:
            src_idx += 1
        if layer is None or getattr(layer, "nested_protocol", None) is None:
            rewritten.append(step)
            continue
        occurrence_cid = layer.occurrence.get("cid") or layer.cid
        body_steps = getattr(layer, "body_steps", ()) or ()
        rewritten.append(
            NestedManagerStepV1(
                nested_protocol=layer.nested_protocol,
                body_steps=body_steps,
                fragment_cid=occurrence_cid,
                occurrence_cid=occurrence_cid,
            )
        )
        rewrote = True
    if not rewrote:
        return frame
    from dataclasses import replace

    from sugar_lift_py_tests.source_call_frame import SourceVisibleCallFrameV1

    if isinstance(frame, SourceVisibleCallFrameV1):
        # Keep the live frame type: SimpleNamespace has no bind_node_actuals,
        # and installed generator Withs consume this object as the source frame.
        return replace(frame, generator_steps=tuple(rewritten))
    return SimpleNamespace(
        frame_cid=frame.frame_cid,
        generator_steps=tuple(rewritten),
        runtime_entries=tuple(getattr(frame, "runtime_entries", ()) or ()),
        parameters=tuple(getattr(frame, "parameters", ()) or ()),
        definition_site=getattr(frame, "definition_site", None),
        owner=owner,
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
    declined=None,
):
    """Construct enter/exit definition sites from generator decorator testimony."""
    from sugar_source_tree.nodes import FunctionDef

    if not isinstance(generator_target, FunctionDef):
        return None
    decorators = getattr(generator_target, "decorators", ()) or ()
    if not decorators:
        return None
    published = []
    # Out-parameter: pass a list and each decorator that could not supply
    # coordinates appends the NAMED reason it could not. Same shape as
    # ``_substitute_body_tracked(..., edge_states=...)``; the return contract is
    # unchanged so existing callers and tests are untouched.
    if declined is None:
        declined = []
    for decorator in decorators:
        outcome = _construct_decorator_function(
            decorator,
            session=session,
            graph=graph,
            dependency_graphs=dependency_graphs,
            distribution_index=distribution_index,
        )
        # Closed set, reconciled here. A citation is NOT a decline-and-forget:
        # it is a named, authenticated identity this road cannot yet consume,
        # and the reason travels so the refusal downstream can say so.
        if isinstance(outcome, DecoratorCitedV1):
            declined.append(
                f"{outcome.module_name}.{outcome.exported_name}: "
                f"{outcome.membrane_kind}"
            )
            continue
        if isinstance(outcome, DecoratorUnresolvedV1):
            declined.append(f"{outcome.kind}: {outcome.detail}")
            continue
        if not isinstance(outcome, DecoratorConstructedV1):
            raise TypeError(
                "decorator resolution must be one of the closed outcomes; "
                f"got {type(outcome).__name__}"
            )
        returned_class = _sole_returned_manager_class(outcome.function)
        if returned_class is None:
            declined.append("decorator body does not return exactly one manager class")
            continue
        coords = _enter_exit_sites_from_class_def(returned_class)
        if coords is None:
            declined.append("returned class publishes no distinct __enter__/__exit__")
            continue
        published.append(coords)
    # Exactly one decorator arm may yield protocol coordinates; several would
    # reintroduce first-candidate selection across independent wrappers.
    if len(published) != 1:
        return None
    return published[0]


@dataclass(frozen=True)
class DecoratorConstructedV1:
    """The decorator resolved to a source-visible FunctionDef we constructed."""

    function: object


@dataclass(frozen=True)
class DecoratorCitedV1:
    """The decorator is authenticated but OFF ENROLLED POPULATION.

    Not an absence: the identity is known and content-addressed. The membrane
    refuses to MaterializeModule it, which is correct -- constructing it would
    invent testimony about a body sugar cannot see. What a consumer may do with
    this citation is a separate ruling; what it may NOT do is mistake it for
    "there was no decorator".
    """

    module_name: str
    exported_name: str
    resolved: object
    membrane_kind: str
    membrane_detail: str | None


@dataclass(frozen=True)
class DecoratorUnresolvedV1:
    """No decorator identity at this site, with the reason named.

    ``absent`` is the only member that means "nothing was there". Every other
    member is a lookup that failed, and the two must never share a value.
    """

    kind: Literal[
        "absent",
        "artifact-authentication-failed",
        "module-absent-from-graph",
        "export-unresolved",
        "frame-construction-gap",
        "not-a-function-definition",
    ]
    detail: str


DecoratorResolutionV1 = (
    DecoratorConstructedV1 | DecoratorCitedV1 | DecoratorUnresolvedV1
)


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
                return DecoratorConstructedV1(binds[0])
        return DecoratorUnresolvedV1(
            "absent", "decorator names no authenticated import or module binding"
        )
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
        except DependencyArtifactAuthenticationError as exc:
            return DecoratorUnresolvedV1(
                "artifact-authentication-failed", f"{module_name}: {exc}"
            )
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
        return DecoratorUnresolvedV1(
            "export-unresolved",
            f"{module_name}.{exported_name} did not resolve in any authenticated graph",
        )
    frame_result = resolve_source_visible_frame(
        resolved,
        graph=resolved_graph,
        dependency_graphs=dependency_graphs,
        session=session,
    )
    if isinstance(frame_result, ManagerConstructionGapV1):
        # OFF-POPULATION IS NOT ABSENCE. The membrane refuses to materialize an
        # unenrolled module -- correctly -- but the identity it refused to
        # construct is authenticated and addressable. Returning None here made
        # that indistinguishable from "there was no decorator", which is how a
        # citable fact became a silent nothing.
        if frame_result.kind == "call-target-off-population":
            return DecoratorCitedV1(
                module_name=module_name,
                exported_name=exported_name,
                resolved=resolved,
                membrane_kind=frame_result.kind,
                membrane_detail=frame_result.detail,
            )
        return DecoratorUnresolvedV1(
            "frame-construction-gap",
            f"{module_name}.{exported_name}: {frame_result.kind}: {frame_result.detail}",
        )
    _frame, target = frame_result
    if not isinstance(target, FunctionDef):
        return DecoratorUnresolvedV1(
            "not-a-function-definition",
            f"{module_name}.{exported_name} resolved to {type(target).__name__}",
        )
    return DecoratorConstructedV1(target)


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


def _direct_with_call_uses(root) -> dict:
    """Direct ``with Call(...)`` uses under ``root``.

    This is the original enrollment route: a With/AsyncWith whose manager
    expression is already a Call at the source occurrence. Projected
    bare-Name managers (``with m:`` after substitute) are collected
    separately; rewritten items that already carry a retained use-site
    are skipped here so they cannot double-enroll.
    """
    from sugar_lift_py_tests.context_manager_resolution import (
        SourceFragmentCoordinateV1,
    )
    from sugar_source_tree.nodes import AsyncWith, Call, With

    uses = {}
    for node in root.walk():
        if not isinstance(node, (With, AsyncWith)):
            continue
        for item in node.items:
            expr = item.context_expr
            if not isinstance(expr, Call):
                continue
            if hasattr(item, "manager_use_site_start_line"):
                continue
            span = expr.line_col_span()
            start_line, start_col, end_line, end_col = item._manager_use_site_span()
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
    return uses


def _seat_projected_manager_call_frame(context, coordinate, call, behavior) -> None:
    """``ctx = cm(); with ctx:`` -- the assignment performs the manager call.

    The With's use coordinate borrowed the reaching assignment's Call
    (``_projected_manager_call_uses``).  That Call is evaluated where it is
    written, once, and ``with ctx`` enters the value it bound; so the derived
    frame is seated on the Call's own coordinate, where the assignment
    constructs it, instead of leaving the assignment an unresolved callee
    whose value the With cannot enter.  Direct ``with cm():`` heads (the use
    coordinate IS the call) are untouched.
    """
    frame = getattr(behavior, "source_call_frame", None)
    if frame is None or not getattr(call, "_borrowed_manager_call", False):
        return
    from .manager_construction import _install_source_call_frame

    _install_source_call_frame(context, call, frame)


def _projected_manager_call_uses(source_file, selected_arms=None):
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

    from sugar_source_tree.nodes import manager_use_projection, selected_manager_calls

    manager_scope_types = (With, AsyncWith)

    # Preserve the original direct-call route exactly.
    uses = _direct_with_call_uses(source_file.root)

    def collect(root, *, projected_names: bool) -> None:
        for node in root.walk():
            if not isinstance(node, manager_scope_types):
                continue
            for item in node.items:
                expr = item.context_expr
                if (
                    projected_names
                    and item.optional_vars is None
                    and expr.kind == "IfExp"
                ):
                    leaves = selected_manager_calls(expr)
                    if leaves is not None:
                        # ``with ctx:`` where ``ctx`` was bound in the arms
                        # of an ``if``: the head is the phi of the arms'
                        # calls.  Each arm's call is its own use, at its own
                        # coordinate (With._selected_manager_sugar).
                        for leaf in leaves:
                            if leaf.kind == "OpaqueObjectStateV1":
                                leaf = leaf.base
                            span = leaf.line_col_span()
                            key = (
                                span.start_line,
                                span.start_col,
                                span.end_line,
                                span.end_col,
                            )
                            object.__setattr__(leaf, "_borrowed_manager_call", True)
                            leaf_coordinate = SourceFragmentCoordinateV1(
                                leaf.unit.source_cid, *key
                            )
                            uses[key] = (leaf_coordinate, leaf, item._exit_face_id())
                            if selected_arms is not None:
                                use_coordinate = SourceFragmentCoordinateV1(
                                    leaf.unit.source_cid, *item._manager_use_site_span()
                                )
                                arms = selected_arms.setdefault(use_coordinate, [])
                                if leaf_coordinate not in arms:
                                    arms.append(leaf_coordinate)
                        continue
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
                object.__setattr__(expr, "_borrowed_manager_call", True)
                uses[(span.start_line, span.start_col, span.end_line, span.end_col)] = (
                    coordinate,
                    expr,
                    item._exit_face_id(),
                )


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
        # No reader has run yet: a ``with ... as`` in the frame exports no
        # binding here rather than demanding a contract nobody has seated.
        with manager_use_projection():
            collect(function.substitute({}), projected_names=True)

    return uses


def _populate_body_defect_kind_detail(exc: BaseException) -> tuple[str, str]:
    """Name a populate-path body defect for cite-and-continue.

    SugarNotWritten → ``source-body-gap`` (existing #7063 arm).
    TypeError → ``source-body-type-error`` (#7062 second costume: construction
    require_* / IfExpSugar post_init failure that used to abort the open and
    bank functionsTotal=0).
    ContextManagerContractError → ``source-body-contract-error`` (a factory
    body that is not a context manager, such as pytest.raises function form,
    must stay a typed gap rather than abort populate).

    Callers must catch only these named classes — never bare ``except``.
    """
    from sugar_lift_py_tests.context_manager_contract import (
        ContextManagerContractError,
    )
    from sugar_source_tree.panic import SugarNotWritten

    if isinstance(exc, SugarNotWritten):
        observed = getattr(exc, "observed", None) or str(exc)
        return "source-body-gap", str(observed)
    if isinstance(exc, TypeError):
        return "source-body-type-error", f"TypeError: {exc}"
    if isinstance(exc, ContextManagerContractError):
        return "source-body-contract-error", str(exc)
    raise TypeError(
        f"_populate_body_defect_kind_detail got unexpected {type(exc).__name__}; "
        f"callers must catch only SugarNotWritten, TypeError, and "
        f"ContextManagerContractError"
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


def _seat_off_population_citation(
    context, coordinate, target_symbol, kind: str, owner_cid: str
) -> bool:
    """Seat the positive citation where an off-population gap would go.

    Derivation reaches this point having AUTHENTICATED the callee and then
    declined to materialize it, because the population membrane refuses to
    rebuild a distribution the pin does not enroll. That is not the same fact
    as failing to find the callee, and it must not produce the same row:
    off-population is "we know exactly which callee this is, and we have
    decided not to look inside it".

    Returns True when the citation was seated, so the caller skips the gap.
    Only a callee citation kind qualifies (``call-target-off-population``,
    ``call-target-c-type-without-source``), and only with a known
    ``target_symbol`` -- a citation naming no callee would claim knowledge we
    do not have, which is the lookup-failure spelling wearing this one's
    clothes.
    """
    from sugar_lift_py_tests.context_manager_resolution import (
        CALLEE_CITATION_KINDS,
        OpaqueSourceCallObligationV1,
        mint_opaque_cited_context_manager_ref,
        opaque_source_call_roster_of,
    )

    if kind not in CALLEE_CITATION_KINDS or not target_symbol:
        return False
    roster = context.opaque_source_call_obligations.get(coordinate)
    if roster is None:
        roster = opaque_source_call_roster_of(
            OpaqueSourceCallObligationV1(
                coordinate,
                str(target_symbol),
                owner_cid,
                kind,
            )
        )
        if kind == "call-target-off-population":
            # The head call is itself an opaque source call.  A C type's
            # construction is not: the head evaluates through its own
            # language-owned floor, so its roster rides only the citation.
            context.opaque_source_call_obligations[coordinate] = roster
    elif roster.resolution_kind != kind:
        # Another owner classified this same call differently. Their testimony
        # stands; do not overwrite it with a citation.
        return False
    context.source_derived_contract_refs[coordinate] = (
        mint_opaque_cited_context_manager_ref(roster=roster)
    )
    return True


def _install_derivation_gap_for_receipt(context, coordinate, receipt, kind, detail=None):
    return _install_derivation_gap(context, coordinate, receipt, kind, detail)


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

    demand_cid = receipt.demand.get("cid", receipt.use["cid"])
    if _seat_off_population_citation(
        context, coordinate, receipt.target_symbol, kind, demand_cid
    ):
        return
    gap = ContextManagerResolutionGapV1(
        demand_cid,
        coordinate,
        receipt.target_symbol,
        kind,
        (),
        detail,
    )
    context.source_derived_contract_refs[coordinate] = gap


def _completed_actual(outcome):
    """The actual a manager's construction receives when it completes.

    An actual that may raise (a two-faced call) halts the ``with`` statement's
    construction, which owns that face (#7599); the manager's behavior is
    derived over the one value its completed face carries.  More than one
    completed face is not one actual."""
    from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet

    if isinstance(outcome, ExitSet):
        completed = [face for face in outcome.exits if isinstance(face, Completed)]
        if len(completed) == 1:
            return Complete(completed[0].value)
    return outcome
