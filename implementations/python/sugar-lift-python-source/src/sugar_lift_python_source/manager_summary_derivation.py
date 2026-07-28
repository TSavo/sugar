"""Project constructed source-manager testimony into the closed CM schema."""

from __future__ import annotations

from dataclasses import dataclass
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
    SuppressesModeV1,
    VariadicKeywordV1,
    VariadicPositionalV1,
    semantics_to_value,
)
from sugar_lift_py_tests.floor import BlockValue, ReturnValue, TermValue
from sugar_lift_py_tests.ir import PrimitiveSort
from sugar_lift_py_tests.outcome import Completed, outcome_to_exitset

from .canonical import cid_of_json
from .manager_protocol_construction import ConstructedManagerProtocolV1


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


def derive_manager_summary(
    protocol: ConstructedManagerProtocolV1,
    *,
    behavior=None,
) -> DerivedManagerSummaryV1 | DerivedManagerSummaryGapV1:
    """Derive only the theorem directly present in constructed outcomes.

    This first arm proves ``NeverSuppresses`` iff every enter face completes
    and every exit face completes with exact Python ``False`` or ``None``.
    Symbolic truthiness remains loud; it is never interpreted by target name.
    """
    from sugar_lift_py_tests.gap.panic import ConstructionPanic

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
        return DerivedManagerSummaryGapV1(
            "exit-may-halt",
            protocol.protocol_construction_cid,
            f"{owner}:{observed}",
        )
    except (OpaqueSourceCallResolutionGap, SugarNotWritten) as exc:
        owner = getattr(exc, "owner", None) or type(exc).__name__
        observed = getattr(exc, "observed", None) or str(exc)
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
    if not exit_.exits or any(not isinstance(face, Completed) for face in exit_.exits):
        return DerivedManagerSummaryGapV1(
            "exit-may-halt", protocol.protocol_construction_cid, "__exit__ ExitSet"
        )
    for face in exit_.exits:
        if not _exact_never_suppresses(face.value):
            return DerivedManagerSummaryGapV1(
                "opaque-exit-truthiness",
                protocol.protocol_construction_cid,
                type(face.value).__name__,
            )
    semantics = ProtocolResourceSemanticsV1(
        EnterResultContractV1(PrimitiveSort("Value")),
        ExitContractV1(NeverSuppressesDispositionV1()),
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

    ``session`` owns every resolution memo for this population; the default
    opens one bounded to this source file.
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

    session = session_or_new(session)
    context = source_file.root.unit.construction_context
    if context is None:
        return
    receipts, _ = authenticated_import_use_receipts(
        Path(root),
        Path(path),
        source_file.unit.source,
        source_file.unit.source_cid,
        module_identities={},
    )
    uses = _projected_manager_call_uses(source_file)
    if selected_coordinates is not None:
        uses = {
            key: value
            for key, value in uses.items()
            if value[0] in selected_coordinates
        }
    graphs = {} if artifact_graph_cache is None else artifact_graph_cache
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
        from .manager_construction import (
            ManagerConstructionGapV1,
            _install_source_call_frame,
            resolve_source_visible_frame,
        )

        frame_result = resolve_source_visible_frame(
            resolved, graph=graph, session=session
        )
        if not isinstance(frame_result, ManagerConstructionGapV1):
            frame, _ = frame_result
            if frame.generator_steps is not None:
                _install_source_call_frame(context, call, frame)
                # Seat the provider Call at the manager-use coordinate so a
                # bare-Name With head resolves through its reaching binding
                # rather than by spelling.  Direct Call heads already key the
                # frame by their own span; the use-site seat is what carries
                # assigned multi-manager projection.
                context.source_manager_provider_calls[coordinate] = call
                continue
        from sugar_lift_py_tests.context.reduce_context import ReduceContext
        from sugar_lift_py_tests.temporal import builtin_name_temporal

        actual_ctx = ReduceContext(temporal=builtin_name_temporal())

        def _actual_outcome(node):
            # Substitution has already replaced every reaching lexical binding.
            # A surviving bare builtin is therefore the language-owned value,
            # not a free formal. NameSugar deliberately represents every other
            # survivor symbolically, so project this one native floor here.
            #
            # Import Attribute exception-class paths (``pkg.Error``) are a
            # second closed projection: the Attribute floor cannot resolve a
            # SymbolicValue module receiver, but ``imported_exception_type_identity``
            # already authenticates the dotted type. Project that identity as
            # the call actual so EffectBoundary managers construct instead of
            # dying at incomplete-call-actuals.
            from sugar_lift_py_tests.floor.authenticated_exception_type_value import (
                AuthenticatedExceptionTypeValue,
            )
            from sugar_lift_py_tests.floor.exception_class_value import (
                ExceptionClassValue,
            )
            from sugar_lift_py_tests.outcome import Complete as _Complete
            from sugar_source_tree.nodes import Attribute, Name

            if isinstance(node, Name):
                builtin = actual_ctx.temporal.value_if_bound(node.id)
                if builtin is not None:
                    return _Complete(builtin)
            if isinstance(node, Attribute):
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
        for node in call.args:
            outcome = _actual_outcome(node)
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
                outcome = _actual_outcome(keyword.value)
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
        behavior = construct_manager_behavior(
            resolved,
            graph=graph,
            actuals=tuple(actuals),
            keyword_actuals=tuple(keyword_actuals),
            call_site=call.fragment,
            session=session,
        )
        from .manager_construction import ConstructedManagerBehaviorV1
        from .manager_protocol_construction import ConstructedManagerProtocolV1

        if not isinstance(behavior, ConstructedManagerBehaviorV1):
            # Stage-keyed residual — never collapse assertion-membrane mass into
            # a single opaque label, and never fuse the stage with its data:
            # `value-call-target` is the key, the callee names are the row.
            kind, detail = _gap_kind_and_detail(behavior)
            _install_derivation_gap(context, coordinate, receipt, kind, detail)
            continue
        protocol = construct_manager_protocol(behavior, exit_face_id=exit_face_id)
        if not isinstance(protocol, ConstructedManagerProtocolV1):
            kind, detail = _gap_kind_and_detail(protocol)
            _install_derivation_gap(context, coordinate, receipt, kind, detail)
            continue
        summary = derive_manager_summary(protocol, behavior=behavior)
        if not isinstance(summary, DerivedManagerSummaryV1):
            kind, detail = _gap_kind_and_detail(summary)
            _install_derivation_gap(context, coordinate, receipt, kind, detail)
            continue
        context.source_derived_contract_refs[coordinate] = (
            SourceDerivedContextManagerRefV1(
                coordinate,
                summary.summary_cid,
                summary.semantics,
                summary.import_signature,
                protocol,
            )
        )


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
    from sugar_source_tree.nodes import Call, With

    uses = {}

    def collect(root, *, projected_names: bool) -> None:
        for node in root.walk():
            if not isinstance(node, With):
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
    from sugar_lift_py_tests.context_manager_resolution import (
        ContextManagerResolutionGapV1,
    )

    context.source_derived_contract_refs[coordinate] = ContextManagerResolutionGapV1(
        receipt.demand.get("cid", receipt.use["cid"]),
        coordinate,
        receipt.target_symbol,
        kind,
        (),
        detail,
    )
