"""Project constructed source-manager testimony into the closed CM schema."""

from __future__ import annotations

from dataclasses import dataclass, replace
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
    VariadicKeywordV1,
    VariadicPositionalV1,
    semantics_to_value,
)
from sugar_lift_py_tests.floor import BlockValue, ReturnValue, TermValue
from sugar_lift_py_tests.floor.branch_result_coordinate import (
    resolve_branch_result_guards as _resolve_branch_result_guards,
)
from sugar_lift_py_tests.ir import PrimitiveSort
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_py_tests.outcome.exit_set import _require_exit_set

from .canonical import cid_of_json
from .manager_protocol_construction import (
    ConstructedManagerProtocolV1,
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
    from sugar_lift_py_tests.outcome import ExitSet

    # A refusal raised while constructing enter or exit propagates as itself;
    # it is never turned into an ``*-may-halt`` gap here.
    enter = protocol.enter_outcome()
    if not isinstance(enter, ExitSet):
        # An undischarged native-operation demand is not an enter face.
        return DerivedManagerSummaryGapV1(
            "enter-may-halt",
            protocol.protocol_construction_cid,
            f"{type(enter).__name__} is not an ExitSet",
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
    exit_outcome = protocol.exit_outcome()
    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )
    from sugar_lift_py_tests.floor.manager_coordinate import ExitValueCoordinate

    # A deferred lookup is not a suppression theorem. Admit only the real
    # source protocol, whose exit will run with each actual With body face.
    # Nor is it an effect boundary: what an attribute of the exit value
    # holds is that value's class's business, never read off the attribute's
    # spelling (#7757). The exit's own return truthiness is the theorem.
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
        semantics = ProtocolResourceSemanticsV1(
            EnterResultContractV1(PrimitiveSort("Value")),
            ExitContractV1(ReturnTruthinessDispositionV1()),
        )
        return _sealed_summary(
            protocol, semantics, _signature_for_behavior(behavior, semantics)
        )
    exit_ = exit_outcome
    if not isinstance(exit_, ExitSet):
        # An undischarged native-operation demand that is not the admitted
        # exit-value lookup above is not an exit face.
        return DerivedManagerSummaryGapV1(
            "exit-may-halt",
            protocol.protocol_construction_cid,
            f"{type(exit_).__name__} is not an ExitSet",
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
    # The operands are read off the exit's own formula. A call the exit made
    # but did not reduce (``self.matches(exc_val)``) is that call's undecided
    # citation: no field or method spelling stands in for its body (#7757).
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
    match_failed_halts = tuple(
        face for face in halted if _halt_complements_true_return(face, exit_set)
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
    if message_index is None and _exit_decision_reads_exit_value(
        formula, exit_set, authentications
    ):
        # The exit decides on the raised value, but no factory formal is the
        # operand it reads: that pattern is unprojected, never
        # NoMessagePattern. Which receiver field holds a pattern is not read
        # off the field's spelling (#7757).
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


def _exit_decision_reads_exit_value(formula, exit_set, authentications):
    """True when the exit's decision mentions the raised value at all.

    The suppression formula, every exit face's guard and every authenticated
    branch guard are read. ``python:exit_value`` anywhere in them means the
    outcome depends on the raised value, so an exit without a projected
    message operand cannot be stated as consuming any message.
    """
    formulas = (
        formula,
        *(face.guard for face in exit_set.exits),
        *(item.observed_guard for item in authentications),
    )
    return any(_formula_mentions_ctor(item, "python:exit_value") for item in formulas)


def _formula_mentions_ctor(formula, name):
    from sugar_lift_py_tests.ir import _Atomic, _Connective

    if isinstance(formula, _Connective):
        return any(_formula_mentions_ctor(item, name) for item in formula.operands)
    if isinstance(formula, _Atomic):
        return any(_term_contains_ctor(arg, name) for arg in formula.args)
    return _term_contains_ctor(formula, name)


def _derive_boundary_for_receiver(protocol, behavior, receiver):
    """Derive one EffectBoundary from a single completed constructor face."""
    specialized = replace(protocol, receiver_state=receiver)
    exit_outcome = specialized.exit_outcome()
    if not isinstance(exit_outcome, ExitSet):
        # An undischarged native-operation demand (a deferred attribute
        # lookup on the exit value included) is not an exit face.
        return None
    return _derive_effect_boundary(exit_outcome, specialized, behavior)


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
        # The boundary continues beneath its receiver face
        # (``ExitSet.sequence``): the face's guard, partition testimony and
        # ``owed`` ride onto it.
        derived.append(
            (
                boundary,
                ExitSet((face,)).sequence(
                    lambda _receiver, boundary=boundary: ExitSet.completed(boundary)
                ),
            )
        )
    none_faces = [
        boundary
        for boundary, _arm in derived
        if isinstance(boundary.message_pattern_operand, NoMessagePatternV1)
    ]
    pattern_faces = [
        boundary
        for boundary, _arm in derived
        if isinstance(
            boundary.message_pattern_operand, OptionalFormalArgumentProjectionV1
        )
    ]
    if not none_faces or not pattern_faces:
        return None
    if len(none_faces) + len(pattern_faces) != len(derived):
        return None
    first = derived[0][0]
    if any(
        boundary.mode != first.mode
        or boundary.effect_kind != first.effect_kind
        or boundary.expected_type_operand != first.expected_type_operand
        or boundary.binding != first.binding
        for boundary, _arm in derived[1:]
    ):
        return None
    pattern_semantics = pattern_faces[0]
    halts = _construction_halts(protocol)
    if halts is None:
        return None
    # Construction halts ride beside the guarded boundary faces: each leaves
    # the With as itself before any boundary is entered. They are siblings of
    # the boundary faces: one join.
    return FactoredEffectBoundarySummaryV1(
        protocol.protocol_construction_cid,
        protocol.enter_frame_cid,
        protocol.exit_frame_cid,
        ExitSet(()).union(*(arm for _boundary, arm in derived), ExitSet(halts)),
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
            # An entry that can halt is not a classified result: refuse.
            if isinstance(statement, ExitSet) and statement.halts():
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
            # A default is read here: a deferred carrier is refused by name.
            outcome = _require_exit_set(
                _declared_default_sugar(frame, index, default_sugar).desugar(),
                owner="ManagerSummary.signature-default",
            )
            constructed = outcome.completed_value()
            # A signature default has no arm to carry an owed item on: an
            # owing default is not constructed completely here.
            if constructed is None or outcome.owed_items():
                raise ValueError("source default did not construct completely")
            raw = json.loads(
                encode_jcs(term_to_value(constructed.to_term(owner=name)))
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


def _declared_default_sugar(frame, index, default_sugar):
    """The default the signature declares for the ``index``-th formal of
    ``frame``: the defining ``def``'s (or lambda's) default expression, the
    one its statement evaluates (``nodes._definition_default_evaluations``).
    A def or lambda frame's own default (``DefaultValueSugar``) is the value
    a call binds, read under a key only a call's binding holds; this reads
    no call.  Any other frame's default is its expression already."""
    from sugar_lift_py_tests.sugar.default_value_sugar import DefaultValueSugar

    if not isinstance(default_sugar, DefaultValueSugar):
        return default_sugar
    return frame.owner.params[index].default.sugar()


def _signature_to_value(signature):
    from sugar_lift_py_tests.context_manager_contract import import_signature_to_value

    return import_signature_to_value(signature)


def _exact_never_suppresses(value: object) -> bool:
    from sugar_lift_py_tests.floor import GuardedReturn
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
        FalseBoolLiteralSugar,
    )
    from sugar_lift_py_tests.sugar.none_literal_sugar import NoneLiteralSugar

    if isinstance(value, BlockValue):
        if value.can_fall_through and not any(
            isinstance(entry, (ReturnValue, GuardedReturn))
            or (isinstance(entry, ExitSet) and entry.halts())
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

    ``session`` owns every resolution memo for this population. Its roster is
    step 2's file list (``project_file_roster``), which this function never
    widens: what the code imports is an edge answered by an imported proof,
    never population (#7796).
    Multi-resolve
    owners (file-open, package enumeration, census walk via ``walk_session_for``)
    must pass one shared session so export/frame amortization is real across
    receipts, consumer files, and same-content re-open under one workspace.

    An imported manager is a coordinate plus an edge: its authenticated
    definition is cited by its import target and its body is never read.
    """
    from pathlib import Path

    from sugar_lift_py_tests.import_binding import (
        authenticated_import_use_receipts,
        authenticated_import_value_use_receipts,
    )

    from .resolution_session import session_or_new

    # Multi-resolve owner entry: one session for every receipt in this loop.
    # Do not call session_or_new inside the receipt loop.
    session = session_or_new(session)
    context =source_file.root.unit.construction_context
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
    paired_receipts = {}
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
            paired_receipts[call_key] = receipt

    graphs = {} if artifact_graph_cache is None else artifact_graph_cache
    # Seed from session so tops already resolved in frame/prefix projection
    # are not re-asked (warnings/re/inspect ×21 on test_pandas).
    if session.enabled:
        for top, graph in session.dependency_graphs.items():
            graphs.setdefault(top, graph)

    def read_imported_head(receipt, coordinate, call, exit_face_id) -> None:
        """The import door: a head whose callee carries an import receipt.

        An imported call is a coordinate plus an edge (step 3): the import
        table's target symbol names the edge, and no dependency source is read
        to decide what the name is.  The manager stands cited by that target;
        an imported proof binds the edge, and where none does it stays
        unanswered.
        """
        _install_derivation_gap(
            context,
            coordinate,
            receipt,
            "call-target-off-population",
            receipt.target_symbol,
        )

    _WithReader(
        source_file.root,
        source_file,
        context,
        uses,
        session=session,
        graphs=graphs,
        value_receipts_by_site=value_receipts_by_site,
        distribution_index=distribution_index,
        selected_arms=selected_arms,
        selected_coordinates=selected_coordinates,
        paired_receipts=paired_receipts,
        read_imported_head=read_imported_head,
    ).read_all()
    _seat_selected_manager_refs(context, selected_arms, selected_coordinates)
    _rewrite_installed_generator_frames(context)


class _WithReader:
    """The one reader of the ``with`` nodes under ``scope``.

    Every ``with`` item is read once, by the derivation the shape of its head
    names:

    - a call whose callee carries an import receipt: the import door
      (``read_imported_head``, which only a module populate holds);
    - a call of a name the module binds nowhere: ``builtins.<name>``, cited;
    - a call of a local Name assigned an import value in every arm: the
      partition of its arms;
    - a call of a name the module binds to one ClassDef: the class door;
    - a call of a module generator, or of a module ``async def``: the
      generator door;
    - a call of a module plain function: the factory door;
    - any other head: a head that only reads a parameter, a chain on a
      call-returned module, or a head a run-time string selects.

    No reader runs over the scope in a fixed order.  The one ordering is a
    dependency, not a sequence: a same-module definition's own ``with`` nodes
    are read before the definition is, because a ``@contextmanager`` whose
    body opens a file builds its frame from that nested row (#7732).
    """

    def __init__(
        self,
        scope,
        source_file,
        context,
        uses,
        *,
        session,
        graphs,
        value_receipts_by_site,
        distribution_index=None,
        selected_arms=None,
        selected_coordinates=None,
        paired_receipts=None,
        read_imported_head=None,
    ):
        from sugar_lift_py_tests.context.reduce_context import ReduceContext
        from sugar_lift_py_tests.temporal import builtin_name_temporal

        self.scope = scope
        self.source_file = source_file
        self.context = context
        self.session = session
        self.graphs = graphs
        self.value_receipts_by_site = value_receipts_by_site
        self.distribution_index = distribution_index
        self.selected_coordinates = selected_coordinates
        self.paired_receipts = paired_receipts or {}
        self.read_imported_head = read_imported_head
        # One reduction context for every same-module constructor this reader
        # applies, as one population always had.
        self.reduce_ctx = ReduceContext(temporal=builtin_name_temporal())
        arm_owner = {
            arm: use_site
            for use_site, arms in (selected_arms or {}).items()
            for arm in arms
        }
        # A head's calls, keyed by the ``with`` item they belong to: the item
        # itself, or the item a branch-selected arm is an arm of.
        self.uses_by_item = {}
        for call_key, (coordinate, call, exit_face_id) in uses.items():
            item_coordinate = arm_owner.get(coordinate, coordinate)
            self.uses_by_item.setdefault(item_coordinate, []).append(
                (call_key, coordinate, call, exit_face_id)
            )
        self.items = {}
        for node, coordinate, item in self._with_items(scope):
            self.items.setdefault(coordinate, (node, item))
        self.read_coordinates = set()
        self.read_definitions = set()
        self.calls_by_start = None

    @staticmethod
    def _with_items(root):
        from sugar_lift_py_tests.context_manager_resolution import (
            SourceFragmentCoordinateV1,
        )
        from sugar_source_tree.nodes import AsyncWith, With

        for node in root.walk():
            if not isinstance(node, (With, AsyncWith)):
                continue
            for item in node.items:
                yield (
                    node,
                    SourceFragmentCoordinateV1(
                        item.context_expr.unit.source_cid,
                        *item._manager_use_site_span(),
                    ),
                    item,
                )

    def read_all(self) -> None:
        for coordinate in tuple(self.items):
            self.read(coordinate)
        for coordinate in tuple(self.uses_by_item):
            self.read(coordinate)

    def read_within(self, definition) -> None:
        """Read the ``with`` nodes inside ``definition`` before it is read."""
        if id(definition) in self.read_definitions:
            return
        self.read_definitions.add(id(definition))
        for _node, coordinate, _item in self._with_items(definition):
            if coordinate in self.items or coordinate in self.uses_by_item:
                self.read(coordinate)

    def read(self, coordinate) -> None:
        """Read one ``with`` item, by its head's shape."""
        from sugar_source_tree.nodes import With

        if coordinate in self.read_coordinates:
            return
        self.read_coordinates.add(coordinate)
        for call_key, use_coordinate, call, exit_face_id in self.uses_by_item.get(
            coordinate, ()
        ):
            self._read_call_head(call_key, use_coordinate, call, exit_face_id)
        entry = self.items.get(coordinate)
        if entry is not None and isinstance(entry[0], With):
            self._read_item_head(coordinate, entry[1])

    def _read_call_head(self, call_key, coordinate, call, exit_face_id) -> None:
        from sugar_source_tree.nodes import (
            AsyncFunctionDef,
            Call,
            ClassDef,
            FunctionDef,
            Name,
        )

        receipt = self.paired_receipts.get(call_key)
        if receipt is not None:
            self.read_imported_head(receipt, coordinate, call, exit_face_id)
            return
        context = self.context
        if coordinate in context.source_derived_contract_refs:
            return
        if not isinstance(call, Call) or not isinstance(call.func, Name):
            return
        if (
            call.unit.builtin_reference_at(call.func.id, call.func.line_col_span())
            is not None
        ):
            _read_builtin_name_head(context, coordinate, call, session=self.session)
            return
        if _read_assigned_partition_head(
            self.source_file,
            context,
            coordinate,
            call,
            value_receipts_by_site=self.value_receipts_by_site,
        ):
            return
        # The callee by the binding the read reaches at its own coordinate
        # (``SourceUnit.module_definition_at``): a parameter, local, free or
        # nonlocal of the function around the call is that binding, never
        # the module's ``def``/``class`` of the same name.
        definition = call.unit.module_definition_at(
            call.func.id, call.func.line_col_span()
        )
        if definition is None:
            return
        if isinstance(definition, ClassDef):
            self.read_within(definition)
            _read_same_module_class_head(
                context,
                coordinate,
                call,
                exit_face_id,
                definition,
                reduce_ctx=self.reduce_ctx,
            )
        elif isinstance(definition, AsyncFunctionDef) or (
            isinstance(definition, FunctionDef)
            and any(
                node.kind in ("Yield", "YieldFrom") for node in definition.walk()
            )
        ):
            self.read_within(definition)
            _read_same_module_generator_head(context, coordinate, call, definition)
        elif type(definition) is FunctionDef:
            _read_same_module_factory_head(
                context,
                coordinate,
                definition,
                value_receipts_by_site=self.value_receipts_by_site,
            )

    def _read_item_head(self, coordinate, item) -> None:
        from sugar_source_tree.formal_manager_head import (
            call_bound_local_manager_head,
            formal_manager_head,
            runtime_selected_manager_head,
        )

        context = self.context
        if coordinate in context.source_derived_contract_refs:
            return
        if (
            self.selected_coordinates is not None
            and coordinate not in self.selected_coordinates
        ):
            return
        unit = self.scope.unit
        start_line, start_col, _end_line, _end_col = item._manager_use_site_span()
        head = formal_manager_head(unit, start_line, start_col)
        if head is not None:
            _read_formal_selected_head(context, coordinate, head)
            return
        if coordinate in context.opaque_source_call_obligations:
            return
        head = call_bound_local_manager_head(unit, start_line, start_col)
        if head is not None and _read_call_bound_module_head(
            context,
            coordinate,
            head,
            calls_by_start=self._calls_by_start(),
            graphs=self.graphs,
            session=self.session,
            distribution_index=self.distribution_index,
        ):
            return
        if (
            coordinate in context.source_derived_contract_refs
            or coordinate in context.opaque_source_call_obligations
        ):
            return
        if runtime_selected_manager_head(unit, start_line, start_col) is not None:
            _read_runtime_selected_head(context, coordinate)

    def _calls_by_start(self) -> dict:
        from sugar_source_tree.nodes import Call

        if self.calls_by_start is None:
            self.calls_by_start = {}
            for candidate in self.scope.walk():
                if isinstance(candidate, Call):
                    span = candidate.line_col_span()
                    self.calls_by_start.setdefault(
                        (span.start_line, span.start_col), candidate
                    )
        return self.calls_by_start


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


def _rewrite_installed_generator_frames(context) -> None:
    """Rewrite seated generator frames after contract refs are published.

    A seated generator (pandas ``assert_produces_warning``, a local ``yield``
    manager, a ``contextlib.contextmanager`` generator) is consumed from
    ``source_call_frames``. Apply the cited-opaque rewrite to those live
    frames once the manager-source refs are seated.

    ``bind_node_actuals`` re-emits steps from the FunctionDef, which would
    drop the rewrite; wrap those frames so bind reapplies it.
    """
    frames = getattr(context, "source_call_frames", None)
    if not frames:
        return
    for coordinate, frame in list(frames.items()):
        if getattr(frame, "generator_steps", None) is None:
            continue
        rewritten = _frame_with_nested_manager_steps(frame)
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
            rewritten = _frame_with_nested_manager_steps(bound)
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


def _read_assigned_partition_head(
    source_file,
    context,
    coordinate,
    call,
    *,
    value_receipts_by_site,
) -> bool:
    """Derive ``with m(...)`` where ``m`` is assigned an import value per arm.

    Reproducer (pandas/_testing/_io.py): ``compress_method`` is bound to
    ``gzip.GzipFile`` / ``bz2.BZ2File`` / ... in an if/elif chain, then used
    once as the manager callee. The call has no receipt (its callee is a local
    Name), so the demand table left it ``runtime-selected``. Every arm,
    however, is an authenticated import value with its own receipt.

    Law: the reaching value of the callee is exactly the set of assignment
    arms when nothing else binds the name in the function. Each arm is cited
    by its import target (the same seat a direct ``with gzip.GzipFile(...)``
    gets); the partition of cited members is minted as one
    ``PartitionedOpaqueCitedContextManagerRefV1``. Anything else stays a loud
    typed gap naming the arm that refused -- never ``runtime-selected``.

    Returns False, having read nothing, when no arm of the callee is an import
    value: the head is not this shape.
    """
    from sugar_lift_py_tests.context_manager_resolution import (
        OpaqueSourceCallObligationV1,
        SourceFragmentCoordinateV1,
        mint_opaque_cited_context_manager_ref,
        mint_partitioned_opaque_cited_context_manager_ref,
        opaque_source_call_roster_of,
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

    function = _enclosing_function(source_file, call)
    if function is None:
        return False
    name = call.func.id
    assignments, other_binders = _name_binders(function, name)
    arms = [(node, arm_receipt(node)) for node in assignments]
    receipted = [(node, receipt) for node, receipt in arms if receipt is not None]
    if not receipted:
        # Not this law's shape: no arm is an import value.
        return False
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
        return True
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
        return True
    members = []
    for node, receipt in receipted:
        member_site = arm_coordinate(node)
        # The member is an imported call: cited by the import table's target
        # symbol (step 3), no dependency source read.
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
    context.source_derived_contract_refs[coordinate] = (
        mint_partitioned_opaque_cited_context_manager_ref(
            use_site=coordinate, members=tuple(members)
        )
    )
    return True




def _constructor_application_from_spread(call_sugar, reduce_ctx):
    """Project typed ``**`` actuals on a local constructor into one application.

    ``SpreadCallSugar`` has no ``.args``/``.keywords`` surface.  Its enrolled
    constructor frame already expands a constructed DictValue through
    ``bind_actuals``; the bound roster is the constructor application.
    """
    from sugar_lift_py_tests.callable_application import CallableApplication
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_source_tree.panic import SugarNotWritten

    outcome = _require_exit_set(
        call_sugar.desugar(reduce_ctx),
        owner="_read_same_module_class_head.collect_application",
    )
    value = outcome.completed_value()
    bound = getattr(value, "bound_source_actuals", None)
    if not isinstance(value, CallSiteValue) or bound is None:
        raise SugarNotWritten(
            owner="_read_same_module_class_head.collect_application",
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
    application = CallableApplication(
        tuple(positional + keyword_values),
        tuple(keyword_names),
        call_sugar.site,
        call_occurrence=getattr(call_sugar, "call_occurrence", None),
    )
    # The application is read off the call's one completed arm, so it
    # continues beneath that arm (``ExitSet.sequence``): it owes what the arm
    # owed and keeps the arm's partition testimony.
    return outcome.sequence(lambda _call: ExitSet.completed(application))


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

    nodes = (*call.args, *(keyword.value for keyword in call.keywords))
    values = tuple(application.arguments)
    if len(nodes) != len(values):
        if any(getattr(keyword, "arg", None) is None for keyword in call.keywords):
            # Typed ``**`` expansion binds more formals than there are
            # syntactic nodes.  Seal each actual against the constructor call
            # fragment rather than inventing a source node per expanded key.
            bindings = []
            for index, value in enumerate(values):
                term_cid = _term_content_cid(value.to_term(owner=term_owner))
                testimony = ConstructedValueTestimonyV1.mint(call.fragment, term_cid)
                coordinate = BindingCoordinateV1.mint(
                    owner_cid, call.fragment, ("constructor-actual", index)
                )
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
        term_cid = _term_content_cid(value.to_term(owner=term_owner))
        testimony = ConstructedValueTestimonyV1.mint(node.fragment, term_cid)
        coordinate = BindingCoordinateV1.mint(
            owner_cid, node.fragment, ("constructor-actual", index)
        )
        bindings.append(
            BindingEntryV1(
                coordinate=coordinate,
                state=node,
                sealed_state=BoundBindingStateV1(testimony),
            )
        )
    return tuple(bindings)



def _receiver_from_constructor_outcome(outcome):
    """Project a class call's outcome to the manager's receiver state.

    ``ClassDefinitionValue.callable_application_with`` applies the constructor
    frame through ``producer_outcome``: each completed face is the call
    retaining the receiver it built, and the constructor's halts are faces of
    the call.  One completed face and no halt is that receiver; otherwise the
    receiver state is the partition of every face, halts included (#7756:
    a construction halt is never dropped on the way to the manager).
    """
    from sugar_lift_py_tests.floor import CallSiteValue, ReceiverStatePartitionValue

    def receiver(value):
        if isinstance(value, CallSiteValue):
            retained = value.retained_source_completion_outcome()
            if retained is not None:
                return _require_exit_set(
                    retained, owner="_receiver_from_constructor_outcome"
                ).completed_value()
        return value

    # The receiver is read off the call's faces: a deferred carrier is
    # refused by name.
    exits = _require_exit_set(outcome, owner="_receiver_from_constructor_outcome")
    completed = exits.completed_value()
    # A bare receiver has no arm to carry an owed item on: an owing face
    # stays a face of the partition, which keeps it.
    if completed is not None and not exits.owed_items():
        return receiver(completed)
    # Each completed face continues as the receiver it retained
    # (``ExitSet.sequence``), keeping its guard, faces and ``owed``; each
    # constructor halt stands as a face of the partition.
    return ReceiverStatePartitionValue(
        exits.sequence(lambda value: ExitSet.completed(receiver(value)))
    )


def _owned_by_class(receiver, class_value) -> bool:
    """The receiver was built by this class statement (its content address).

    The class call re-reduces its own class statement, so the receiver's class
    value is that statement's, equal by ``class_definition_cid``, not the
    caller's object.
    """
    defining = getattr(receiver, "defining_class", None)
    return defining is not None and (
        getattr(defining, "class_definition_cid", None)
        == class_value.class_definition_cid
    )


def _read_same_module_class_head(
    context, coordinate, call, exit_face_id, class_def, *, reduce_ctx
) -> None:
    """Derive the CM contract of ``with C(...)`` for a same-module ClassDef.

    Import receipts never fire for local constructors. When Call.func Name
    binds to exactly one module ClassDef, construct the instance via the
    ordinary Call floor (force_floor), then protocol + summary + native
    enter/exit publication — one pipeline with the import-backed door.
    """
    from sugar_lift_py_tests.context_manager_resolution import (
        SourceDerivedContextManagerRefV1,
    )
    from sugar_lift_py_tests.floor import ObjectValue
    from sugar_lift_py_tests.callable_application import CallableApplication
    from sugar_lift_py_tests.floor import (
        ClassDefinitionValue,
        ReceiverStatePartitionValue,
    )
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

    def collect_application(call_sugar):
        """Collect authenticated call actuals without re-entering Call.sugar()."""
        from sugar_lift_py_tests.sugar.spread_sugar import SpreadCallSugar

        if isinstance(call_sugar, SpreadCallSugar):
            return _constructor_application_from_spread(call_sugar, reduce_ctx)

        if not (hasattr(call_sugar, "args") and hasattr(call_sugar, "keywords")):
            # A spread/starred manager call (``with LocalClass(*args): ...``)
            # constructs a SpreadCallSugar with no positional/keyword actual
            # surface.  Refuse by name (the refusal propagates as itself)
            # rather than crashing with a bare AttributeError that voids the
            # whole file as an instrument failure.
            raise SugarNotWritten(
                owner="_read_same_module_class_head.collect_application",
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
                return ExitSet.completed(
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

    target_symbol = f"python:local:{class_def.name}"
    # The class, the call's actuals and the call's result are each read
    # here: a deferred native-operation carrier is refused by name, and a
    # refusal raised while reading them propagates as itself (#7757 item 4).
    class_outcome = _require_exit_set(
        class_def.sugar().desugar(reduce_ctx),
        owner="_read_same_module_class_head",
    )
    class_value = class_outcome.completed_value()
    if type(class_value) is not ClassDefinitionValue:
        _install_local_derivation_gap(
            context,
            coordinate,
            target_symbol,
            "class-definition-not-constructed",
            type(class_outcome).__name__,
        )
        return
    application = _require_exit_set(
        collect_application(call.sugar()),
        owner="_read_same_module_class_head",
    )
    application_value = application.completed_value()
    # The manager behavior built from these actuals has no arm to
    # carry an owed item on: an owing application is not constructed.
    if application_value is None or application.owed_items():
        _install_local_derivation_gap(
            context, coordinate, target_symbol,
            "call-arguments-not-constructed", type(application).__name__
        )
        return
    result_outcome = class_value.callable_application_with(
        application_value, reduce_ctx
    )
    result = _receiver_from_constructor_outcome(result_outcome)
    if isinstance(result, ObjectValue):
        if not _owned_by_class(result, class_value):
            _install_local_derivation_gap(
                context,
                coordinate,
                target_symbol,
                "class-definition-provenance-mismatch",
                "constructed receiver is not owned by authenticated class_def",
            )
            return
    elif isinstance(result, ReceiverStatePartitionValue):
        leaves = _completed_object_receivers(result)
        if not leaves or any(
            not _owned_by_class(leaf, class_value)
            for leaf in leaves
        ):
            _install_local_derivation_gap(
                context,
                coordinate,
                target_symbol,
                "class-definition-provenance-mismatch",
                "constructed receiver is not owned by authenticated class_def",
            )
            return
    else:
        _install_local_derivation_gap(
            context,
            coordinate,
            target_symbol,
            "non-manager-result",
            type(result).__name__,
        )
        return
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
        return
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
    protocol = construct_manager_protocol(behavior, exit_face_id=exit_face_id)
    if not isinstance(protocol, ConstructedManagerProtocolV1):
        if _publish_proven_non_manager_head(
            context,
            coordinate,
            call,
            class_def,
            protocol,
            construction_total=not result_outcome.owed_items()
            and isinstance(result_outcome.completed_value(), ObjectValue),
        ):
            return
        kind, detail = _gap_kind_and_detail(protocol)
        _install_local_derivation_gap(
            context, coordinate, target_symbol, kind, detail
        )
        return
    summary = derive_manager_summary(protocol, behavior=behavior)
    if not isinstance(summary, DerivedManagerSummaryV1):
        kind, detail = _gap_kind_and_detail(summary)
        _install_local_derivation_gap(
            context, coordinate, target_symbol, kind, detail
        )
        return
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


def _read_same_module_factory_head(
    context,
    coordinate,
    function_def,
    *,
    value_receipts_by_site,
) -> None:
    """``with f(...)`` where ``f`` is this module's plain factory.

    ``pandas.io.common.urlopen`` is ``import urllib.request`` then ``return
    urllib.request.urlopen(*args, **kwargs)``: the manager the With enters is
    that vendor call's result.  The returned call's callee carries an
    authenticated import value receipt, and the manager is cited by that
    receipt's target symbol (step 3), never materialized and no dependency
    source read: the With keeps Python's law with enter, exit and suppression
    open and two-faced (``WithOpaqueCitedManagerSugar``), and the head still
    runs the factory's own body.  Any other return shape, or a callee with no
    import receipt, is left for ``With`` to refuse.
    """
    from sugar_lift_py_tests.context_manager_resolution import (
        OpaqueSourceCallObligationV1,
        OpaqueSourceCallRosterV1,
        mint_opaque_cited_context_manager_ref,
    )

    if function_def.decorators:
        return
    returned = _same_module_factory_return(function_def)
    if returned is None:
        return
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
        return
    roster = OpaqueSourceCallRosterV1(
        coordinate,
        receipt.target_symbol,
        "call-target-off-population",
        (
            OpaqueSourceCallObligationV1(
                coordinate,
                receipt.target_symbol,
                receipt.demand.get("cid", receipt.use["cid"]),
                resolution_kind="call-target-off-population",
            ),
        ),
    )
    context.source_derived_contract_refs[coordinate] = (
        mint_opaque_cited_context_manager_ref(roster=roster)
    )


def _read_same_module_generator_head(context, coordinate, call, function_def) -> None:
    """Seat ``with g(...)``'s frame where the call of ``g`` applies it.

    Import receipts never fire for a local callee.  Whether a call of the
    module generator function ``g`` runs ``g``'s own frame is the one decorator
    application's rule (``call_applies_own_frame``, #7757), never read here
    from a decorator's spelling or body:

    - an undecorated generator function returns the generator object itself,
      which has no ``__enter__``: the frame is seated so the With constructs
      the interpreter's own TypeError (#7595), never a manager and never a
      runtime-selected gap;
    - a generator function whose one decorator is bound to
      ``contextlib.contextmanager`` builds ``_GeneratorContextManager`` over
      the generator its frame allocates: the frame is seated and the With
      applies contextlib's law to it (``GeneratorWithSugar``,
      ``generator_manager_exit``).  This is the only decorated definition
      whose call keeps its frame;
    - every other decorated definition binds its name to its decorators'
      result, and a call of it calls that value (``DecoratorApplicationSugar``).
      Nothing is seated: what a decorator returns is not decided here, and the
      With's require door refuses the head by name.
    """
    from sugar_source_tree.nodes import call_applies_own_frame

    from .manager_construction import _install_source_call_frame

    if not call_applies_own_frame(function_def):
        return
    # A refusal building the frame propagates as itself.
    frame, _generator_target = _source_visible_frame_for_function(function_def)
    if frame is None or frame.generator_steps is None:
        # Not a generator: the require door owns it.
        return
    _install_source_call_frame(context, call, frame)
    context.source_manager_provider_calls[coordinate] = call


def _read_builtin_name_head(context, coordinate, call, *, session) -> None:
    """``with open(...)``: a head calling a builtin name is not bridged.

    Import receipts never fire for a builtin name.  When the unit resolves the
    head's callee name to the builtin namespace (``builtin_reference_at``),
    the callee is ``builtins.<name>``.  No artifact
    authenticates ``builtins``, so the lifter does not have it: the manager is
    cited naming ``python:builtins.<name>``, exactly as any other callee the
    lifter does not have.  What it is implemented in is never asked.
    """
    from .manager_construction import _graph_is_off_population

    if not _graph_is_off_population(None, session=session, module_name="builtins"):
        return
    target_symbol = f"python:builtins.{call.func.id}"
    _seat_off_population_citation(
        context,
        coordinate,
        target_symbol,
        "call-target-off-population",
        cid_of_json(
            {
                "kind": "builtin-name-callee",
                "schemaVersion": "1",
                "targetSymbol": target_symbol,
                "useSite": coordinate.wire(),
            }
        ),
    )


def _read_formal_selected_head(context, coordinate, head) -> None:
    """Seat the opaque two-faced manager at ``with p.m():`` / ``with self.x:``.

    Nothing in the frame knows the type of the object a parameter holds, so no
    derivation can name its ``__enter__``/``__exit__``.  When the head only
    reads that parameter through attribute reads and constant-argument calls,
    the manager is opaque and keyed on the With's site: construction, enter
    and exit are two-faced and suppression is the undecided truth of the
    exit result.
    """
    from .formal_selected_manager import mint_formal_selected_manager_ref

    context.source_derived_contract_refs[coordinate] = (
        mint_formal_selected_manager_ref(coordinate, head)
    )


def _returned_floors(value, depth: int = 0) -> tuple:
    """The floors a completed call value can be, read through its return arms.

    A body-bearing call carries the completion its source body retained: a
    single floor, or a ``BlockValue`` whose ``ReturnValue``/``GuardedReturn``
    entries are the arms it can return by (nested blocks are read the same
    way; an arm that halts returns nothing).  Anything else -- an opaque call,
    a body whose completion was not retained -- is returned as itself, so the
    caller sees it and refuses to call it a module.
    """
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.floor.call_site_value import (
        CallSiteValue,
        _RetainedSourceCompletionV1,
    )
    from sugar_lift_py_tests.floor.guarded_return import GuardedReturn
    from sugar_lift_py_tests.floor.return_value import ReturnValue

    if depth > 32:
        return (value,)
    if isinstance(value, CallSiteValue):
        retained = value._retained_source_completion
        if type(retained) is not _RetainedSourceCompletionV1:
            return (value,)
        return _returned_floors(retained.value, depth + 1)
    if isinstance(value, BlockValue):
        floors = []
        for entry in value.statements:
            if isinstance(entry, (ReturnValue, GuardedReturn)):
                floors.extend(_returned_floors(entry.value, depth + 1))
            elif isinstance(entry, BlockValue):
                floors.extend(_returned_floors(entry, depth + 1))
        return tuple(floors)
    return (value,)


def _module_returned_by_call(call) -> str | None:
    """The one module ``call`` returns on every completed face that is not None.

    The call is reduced through its own sugar (the same reduction the function
    body runs); a source callee's completion is split per return arm, each arm
    carrying its own returned floor.  The answer is ``<name>`` only when every
    completed face returns either ``None`` or the module coordinate
    ``python:module(<name>)`` -- the value ``importlib.import_module`` of a
    present module completes with (#7742) -- and at least one returns it.  Any
    other value (an opaque result, a string, two different modules) is not a
    module, and answers None.  A reduction that refuses propagates its refusal
    by name.
    """
    from sugar_lift_py_tests.context.reduce_context import ReduceContext
    from sugar_lift_py_tests.floor.none_value import NoneValue
    from sugar_lift_py_tests.outcome import Completed
    from sugar_lift_py_tests.source_call_resolution import module_value_name
    from sugar_lift_py_tests.temporal import builtin_name_temporal

    ctx = ReduceContext(temporal=builtin_name_temporal())
    exits = _require_exit_set(
        call.sugar().desugar(ctx), owner="_module_returned_by_call"
    ).exits
    values = []
    for face in exits:
        if isinstance(face, Completed):
            values.extend(_returned_floors(face.value))
    modules = set()
    for value in values:
        if type(value) is NoneValue:
            continue
        name = module_value_name(value)
        if name is None:
            return None
        modules.add(name)
    if len(modules) != 1:
        return None
    (name,) = modules
    return name


def _read_call_bound_module_head(
    context,
    coordinate,
    head,
    *,
    calls_by_start,
    graphs,
    session,
    distribution_index,
) -> bool:
    """Cite the manager a call-returned off-population module's chain produces.

    ``zstd = import_optional_dependency("zstandard", errors="ignore")`` then
    ``with zstd.ZstdDecompressor().stream_reader(b"") as reader:``
    (``pandas.io.common._get_binary_io_classes``, #7742).  The local's value is
    read from its binding call: when that call returns, on every non-None
    face, the one module ``M`` (``_module_returned_by_call``), the head is a
    chain on ``M`` whose first step reads ``M.<attr>``.  When ``M``'s
    distribution is off the enrolled population (a third-party package, or
    CPython's own), the manager the chain produces is that package's object,
    which is not looked at: it is cited over the existing
    ``OpaqueCitedContextManagerRefV1`` naming ``python:M.<attr>`` with kind
    ``call-target-off-population``, exactly as a factory returning an
    off-population callee's result is (``_read_same_module_factory_head``).
    Enter and exit stay two-faced, suppression undecided, a body raise still
    propagates, and the head itself still evaluates through its own sugar (its
    roster rides only the citation).  A module on the population, a value that
    is not a module, or a binder that is not a call of the reader's scope is
    left alone, and False is returned.

    ``head`` is ``call_bound_local_manager_head``'s answer: the binder call's
    start and the attribute the chain first reads.  ``calls_by_start`` is the
    reader's scope's calls, keyed by start.
    """
    from sugar_lift_py_tests.context_manager_resolution import (
        OpaqueSourceCallObligationV1,
        OpaqueSourceCallRosterV1,
        _hash_json,
        mint_opaque_cited_context_manager_ref,
    )

    from .dependency_artifact import DependencyArtifactAuthenticationError
    from .manager_construction import (
        _dependency_graph_for_top,
        _graph_is_off_population,
    )

    binder_start, attribute = head
    binder = calls_by_start.get(binder_start)
    if binder is None:
        return False
    module_name = _module_returned_by_call(binder)
    if module_name is None:
        return False
    top_level = module_name.split(".", 1)[0]
    try:
        graph = graphs.get(top_level) or _dependency_graph_for_top(
            top_level,
            session=session,
            dependency_graphs=graphs,
            distribution_index=distribution_index,
        )
    except DependencyArtifactAuthenticationError:
        return False
    if not _graph_is_off_population(graph, session=session, module_name=module_name):
        return False
    target = f"python:{module_name}.{attribute}"
    owner_cid = _hash_json(
        {
            "kind": "call-bound-module-head-demand",
            "useSite": coordinate.wire(),
            "target": target,
        }
    )
    roster = OpaqueSourceCallRosterV1(
        coordinate,
        target,
        "call-target-off-population",
        (
            OpaqueSourceCallObligationV1(
                coordinate,
                target,
                owner_cid,
                resolution_kind="call-target-off-population",
            ),
        ),
    )
    context.source_derived_contract_refs[coordinate] = (
        mint_opaque_cited_context_manager_ref(roster=roster)
    )
    return True


def _read_runtime_selected_head(context, coordinate) -> None:
    """Cite the manager at a head whose value a run-time string selects.

    ``klass = getattr(module, klass)`` then ``with klass(path) as f:``: which
    class stands at the head is chosen by a string at run time, so there is no
    callee for any derivation to read.  The With is constructed over the
    existing opaque citation (enter, exit and suppression open and two-faced;
    the head itself still evaluates through its own sugar).  The citation names
    no callee -- it has none -- only the head's own coordinate and the reason
    kind ``head-runtime-selected``.  The reader reaches it only for a head no
    other derivation seated (a construction or its gap), so it never cites
    over one.
    """
    from sugar_lift_py_tests.context_manager_resolution import (
        OpaqueSourceCallObligationV1,
        _hash_json,
        mint_opaque_cited_context_manager_ref,
        opaque_source_call_roster_of,
    )

    owner_cid = _hash_json(
        {
            "kind": "runtime-selected-head-demand",
            "useSite": coordinate.wire(),
        }
    )
    roster = opaque_source_call_roster_of(
        OpaqueSourceCallObligationV1(coordinate, "", owner_cid, "head-runtime-selected")
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


def _source_visible_frame_for_function(function_def):
    """Build (frame, FunctionDef) for a same-module generator FunctionDef."""
    from sugar_source_tree.nodes import AsyncFunctionDef, FunctionDef

    if not isinstance(function_def, (FunctionDef, AsyncFunctionDef)):
        return None, None
    frame = function_def.source_visible_call_frame()
    if frame is None:
        return None, None
    return frame, function_def


def _nameable_nested_with_body_steps(body, *, scope=None) -> tuple | None:
    """A nested With body's generator steps, named by the one step producer.

    ``FunctionDef._generator_step_producer`` names each statement exactly as
    it names a top-level generator body's (yield, yield assignment, yield
    from, assign, attribute assign, assert, import, raise, term, for, while,
    if, try/finally, try/except around one yield).  A ``with`` inside the
    body is the cited-opaque manager this module resolves
    (``_cited_opaque_nested_step_for``, NestedCitedOpaqueManagerStepV1).

    Returns None when any statement is unnameable, which keeps the nested
    With loud.  A statement whose sugar is not written refuses by name
    (``SugarNotWritten`` propagates).  Does not invent items, warning
    testimony, a bound on ``while True``, a loaded module, that an attribute
    was stored, or that a cleanup raise was suppressed.
    """
    from sugar_source_tree.nodes import FunctionDef

    _name_statement, branch_steps = FunctionDef._generator_step_producer(
        with_step=lambda statement: _cited_opaque_nested_step_for(
            statement, scope=scope
        )
    )
    return branch_steps(tuple(body))


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
    manager_sugar = item.context_expr.sugar()
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


def _frame_with_nested_manager_steps(frame):
    """Rewrite Opaque With steps when a cited-opaque With resolves.

    Producer-owned: does not edit nodes.py emission. Leaves the frame unchanged
    when there is nothing to rewrite.
    """
    from types import SimpleNamespace

    from sugar_lift_py_tests.generator_construction import OpaqueStepV1
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
    if not cited_by_cid:
        return frame
    rewritten = []
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
        if cited is None:
            rewritten.append(step)
            continue
        rewritten.append(cited)
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
                item._source_exit_face_id(),
            )
    return uses


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

    from sugar_source_tree.nodes import selected_manager_calls

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
                            uses[key] = (
                                leaf_coordinate,
                                leaf,
                                item._source_exit_face_id(),
                            )
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
                    item._source_exit_face_id(),
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
        # No reader has run yet.  A ``with ... as name`` in the frame binds
        # ``name`` without demanding a row nobody has seated
        # (``With.substitution_binding``): the projection is substitution as
        # every caller has it, with no mode of its own.
        collect(function.substitute({}), projected_names=True)

    return uses


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
    Only a callee citation kind qualifies (``call-target-off-population``:
    the callee is not bridged), and only with a known
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
        # The head call is itself the not-bridged call: it stands as its
        # call-site coordinate, completing opaque or raising undetermined.
        context.opaque_source_call_obligations[coordinate] = roster
    elif roster.resolution_kind != kind:
        # Another owner classified this same call differently. Their testimony
        # stands; do not overwrite it with a citation.
        return False
    context.source_derived_contract_refs[coordinate] = (
        mint_opaque_cited_context_manager_ref(roster=roster)
    )
    return True


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
