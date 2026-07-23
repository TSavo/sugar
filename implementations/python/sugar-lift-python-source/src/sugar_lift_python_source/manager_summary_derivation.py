"""Project constructed source-manager testimony into the closed CM schema."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Literal

from sugar_lift_py_tests.canonicalizer import encode_jcs
from sugar_lift_py_tests.context_manager_contract import (
    EnterResultContractV1,
    ExitContractV1,
    NeverSuppressesDispositionV1,
    ProtocolResourceSemanticsV1,
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
    semantics: ProtocolResourceSemanticsV1
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
    preimage = {
        "kind": "source-derived-context-manager-summary",
        "schemaVersion": "1",
        "protocolConstructionCid": protocol.protocol_construction_cid,
        "enterTestimonyCid": protocol.enter_frame_cid,
        "exitTestimonyCid": protocol.exit_frame_cid,
        "semantics": json.loads(encode_jcs(semantics_to_value(semantics))),
    }
    return DerivedManagerSummaryV1(
        protocol.protocol_construction_cid,
        protocol.enter_frame_cid,
        protocol.exit_frame_cid,
        semantics,
        cid_of_json(preimage),
    )


def _exact_never_suppresses(value: object) -> bool:
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
        FalseBoolLiteralSugar,
    )
    from sugar_lift_py_tests.sugar.none_literal_sugar import NoneLiteralSugar

    if isinstance(value, BlockValue):
        if not value.statements or not isinstance(value.statements[-1], ReturnValue):
            return False
        value = value.statements[-1].value
    if isinstance(value, (FalseBoolLiteralSugar, NoneLiteralSugar)):
        return True
    return isinstance(value, TermValue) and (
        value.value is None or type(value.value) is bool and value.value is False
    )


def populate_source_derived_resource_refs(
    source_file, *, root, path, distribution_index=None
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
        distribution = (
            importlib.metadata.distribution(distributions[0])
            if distribution_index is None
            else distribution_index[top_level]
        )
        graph = DependencyArtifactGraph.authenticate(distribution)
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
        summary = derive_manager_summary(protocol)
        if not isinstance(summary, DerivedManagerSummaryV1):
            _install_derivation_gap(context, coordinate, receipt, "no-derived-contract")
            continue
        context.source_derived_contract_refs[coordinate] = (
            SourceDerivedContextManagerRefV1(
                coordinate, summary.summary_cid, summary.semantics, protocol
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
