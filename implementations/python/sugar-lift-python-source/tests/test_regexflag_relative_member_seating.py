"""Exact receipt transport for ``re.RegexFlag`` imported class fields."""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor.import_member_value import ImportMemberValue
from sugar_lift_python_source.dependency_artifact import DependencyArtifactGraph
from sugar_lift_python_source.manager_construction import (
    _seat_import_value_use_receipts,
)
from sugar_lift_python_source.resolution_session import SourceResolutionSession
from sugar_source_tree.nodes import Attribute, ClassDef
from sugar_source_tree.panic import BackendDefect, SugarNotWritten
from sugar_source_tree.tree import SourceFile


def test_regexflag_relative_member_receipt_survives_repeated_frame_seating() -> None:
    graph = DependencyArtifactGraph.authenticate_stdlib_module("re")
    module = graph.modules["re"]
    context = TreeConstructionContextV1.for_source_call_construction()
    source_file = SourceFile(
        (module.source, module.source_seat, module.source_cid),
        construction_context=context,
    )
    regex_flag = next(
        node
        for node in source_file.root.body
        if isinstance(node, ClassDef) and node.name == "RegexFlag"
    )
    session = SourceResolutionSession(enabled=False)

    for _ in range(2):
        _seat_import_value_use_receipts(
            source_file=source_file,
            module=module,
            target=regex_flag,
            session=session,
            context=context,
            dependency_graphs={"re": graph},
        )

    member = next(
        node
        for node in source_file.nodes()
        if isinstance(node, Attribute)
        and node.attr == "SRE_FLAG_ASCII"
        and node.line_col_span().start_line == 145
    )
    outcome = member.sugar().desugar()
    assert type(outcome.value) is ImportMemberValue
    assert outcome.value.qualified_name == "re._compiler.SRE_FLAG_ASCII"
    assert any(
        outcome.value.receipt is receipt
        for receipt in context.source_import_value_receipts[
            (module.module_name, module.source_seat, module.source_cid)
        ]
    )


def test_regexflag_relative_member_missing_foreign_and_crosswired_receipts_refuse() -> (
    None
):
    graph = DependencyArtifactGraph.authenticate_stdlib_module("re")
    module = graph.modules["re"]
    context = TreeConstructionContextV1.for_source_call_construction()
    source_file = SourceFile(
        (module.source, module.source_seat, module.source_cid),
        construction_context=context,
    )
    regex_flag = next(
        node
        for node in source_file.root.body
        if isinstance(node, ClassDef) and node.name == "RegexFlag"
    )
    member = next(
        node
        for node in source_file.nodes()
        if isinstance(node, Attribute)
        and node.attr == "SRE_FLAG_ASCII"
        and node.line_col_span().start_line == 145
    )
    with pytest.raises(SugarNotWritten, match="SymbolicValue.attribute"):
        member.sugar().desugar()

    _seat_import_value_use_receipts(
        source_file=source_file,
        module=module,
        target=regex_flag,
        session=SourceResolutionSession(enabled=False),
        context=context,
        dependency_graphs={"re": graph},
    )
    receipt = next(
        row
        for row in context.source_import_value_receipts[
            (module.module_name, module.source_seat, module.source_cid)
        ]
        if row.target_symbol == "python:re._compiler.SRE_FLAG_ASCII"
    )
    span = member.line_col_span()
    exact = (span.start_line, span.start_col, span.end_line, span.end_col)
    with pytest.raises(BackendDefect, match="does not match exact value-use seat"):
        source_file.unit.seat_import_value_use_resolution(
            (exact[0], exact[1], exact[2], exact[3] - 1),
            receipt,
            source_cid=module.source_cid,
        )
    with pytest.raises(BackendDefect, match="this unit only"):
        source_file.unit.seat_import_value_use_resolution(
            exact,
            receipt,
            source_cid="blake3-512:" + "0" * 128,
        )
