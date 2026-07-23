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
    enter = outcome_to_exitset(protocol.enter_outcome())
    if not enter.exits or any(not isinstance(face, Completed) for face in enter.exits):
        return DerivedManagerSummaryGapV1(
            "enter-may-halt", protocol.protocol_construction_cid, "__enter__ ExitSet"
        )
    exit_ = outcome_to_exitset(protocol.exit_outcome())
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
    if not predicates or any(
        predicate != predicates[0] for predicate in predicates[1:]
    ):
        return None
    formula = predicates[0]
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
    source_frame_cache: dict | None = None,
) -> None:
    """Preconstruct imported resource managers and freeze exact use-site rows."""
    import importlib.metadata
    from pathlib import Path

    from sugar_lift_py_tests.context_manager_resolution import (
        ContextManagerResolutionGapV1,
        SourceDerivedContextManagerRefV1,
        SourceFragmentCoordinateV1,
    )
    from sugar_lift_py_tests.import_binding import authenticated_import_use_receipts
    from sugar_lift_py_tests.ir import _term_content_cid
    from sugar_lift_py_tests.outcome import Complete
    from sugar_source_tree.binding_provenance import ConstructedValueTestimonyV1
    from sugar_source_tree.nodes import Call, With

    from .dependency_artifact import (
        DependencyArtifactGraph,
        ResolvedPythonObjectV1,
        resolve_import_binding,
    )
    from .manager_construction import (
        ConstructedCallActualV1,
        construct_manager_behavior,
    )
    from .manager_protocol_construction import construct_manager_protocol

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
    uses = {}
    for node in source_file.nodes():
        if not isinstance(node, With):
            continue
        for item in node.items:
            expr = item.context_expr
            if not isinstance(expr, Call):
                continue
            span = expr.line_col_span()
            coordinate = SourceFragmentCoordinateV1(
                expr.unit.source_cid,
                span.start_line,
                span.start_col,
                span.end_line,
                span.end_col,
            )
            uses[(span.start_line, span.start_col, span.end_line, span.end_col)] = (
                coordinate,
                expr,
                item._exit_face_id(),
            )
    packages = (
        importlib.metadata.packages_distributions()
        if distribution_index is None
        else {name: (name,) for name in distribution_index}
    )
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
        distributions = tuple(packages.get(top_level, ()))
        if len(distributions) != 1:
            _install_derivation_gap(context, coordinate, receipt, "no-derived-contract")
            continue
        graph = graphs.get(top_level)
        if graph is None:
            distribution = (
                importlib.metadata.distribution(distributions[0])
                if distribution_index is None
                else distribution_index[top_level]
            )
            graph = DependencyArtifactGraph.authenticate(distribution)
            graphs[top_level] = graph
        resolved = resolve_import_binding(receipt, graph=graph)
        if not isinstance(resolved, ResolvedPythonObjectV1):
            _install_derivation_gap(context, coordinate, receipt, "no-derived-contract")
            continue
        actuals = []
        for node in call.args:
            outcome = node.sugar().desugar()
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
                outcome = keyword.value.sugar().desugar()
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
            _install_derivation_gap(context, coordinate, receipt, "no-derived-contract")
            continue
        behavior = construct_manager_behavior(
            resolved,
            graph=graph,
            actuals=tuple(actuals),
            keyword_actuals=tuple(keyword_actuals),
            call_site=call.fragment,
            source_frame_cache=source_frame_cache,
        )
        from .manager_construction import ConstructedManagerBehaviorV1
        from .manager_protocol_construction import ConstructedManagerProtocolV1

        if not isinstance(behavior, ConstructedManagerBehaviorV1):
            _install_derivation_gap(context, coordinate, receipt, "no-derived-contract")
            continue
        protocol = construct_manager_protocol(behavior, exit_face_id=exit_face_id)
        if not isinstance(protocol, ConstructedManagerProtocolV1):
            _install_derivation_gap(context, coordinate, receipt, "no-derived-contract")
            continue
        summary = derive_manager_summary(protocol, behavior=behavior)
        if not isinstance(summary, DerivedManagerSummaryV1):
            _install_derivation_gap(context, coordinate, receipt, "no-derived-contract")
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


def _install_derivation_gap(context, coordinate, receipt, kind: str) -> None:
    from sugar_lift_py_tests.context_manager_resolution import (
        ContextManagerResolutionGapV1,
    )

    context.source_derived_contract_refs[coordinate] = ContextManagerResolutionGapV1(
        receipt.demand.get("cid", receipt.use["cid"]),
        coordinate,
        receipt.target_symbol,
        kind,
        (),
    )
