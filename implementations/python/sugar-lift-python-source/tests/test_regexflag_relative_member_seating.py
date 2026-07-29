"""Exact receipt transport for ``re.RegexFlag`` imported class fields."""

from __future__ import annotations

from dataclasses import replace

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


def test_regexflag_receipt_transports_across_exact_parser_owned_units() -> None:
    graph = DependencyArtifactGraph.authenticate_stdlib_module("re")
    module = graph.modules["re"]
    context = TreeConstructionContextV1.for_source_call_construction()
    first = SourceFile(
        (module.source, module.source_seat, module.source_cid),
        construction_context=context,
    )
    second = SourceFile(
        (module.source, module.source_seat, module.source_cid),
        construction_context=context,
    )
    renamed = SourceFile(
        (module.source, "renamed/__init__.py", module.source_cid),
        construction_context=context,
    )
    regex_flag = next(
        node
        for node in first.root.body
        if isinstance(node, ClassDef) and node.name == "RegexFlag"
    )
    _seat_import_value_use_receipts(
        source_file=first,
        module=module,
        target=regex_flag,
        session=SourceResolutionSession(enabled=False),
        context=context,
        dependency_graphs={"re": graph},
    )

    def ascii_member(source_file: SourceFile) -> Attribute:
        return next(
            node
            for node in source_file.nodes()
            if isinstance(node, Attribute)
            and node.attr == "SRE_FLAG_ASCII"
            and node.line_col_span().start_line == 145
        )

    first_value = ascii_member(first).sugar().desugar().value
    second_value = ascii_member(second).sugar().desugar().value

    assert type(first_value) is ImportMemberValue
    assert type(second_value) is ImportMemberValue
    assert second_value.receipt is first_value.receipt
    with pytest.raises(SugarNotWritten, match="SymbolicValue.attribute"):
        ascii_member(renamed).sugar().desugar()
    exact_rows = context.source_import_value_receipts_by_site
    assert len(exact_rows) > 1
    assert all(key[0] == module.source_seat for key in exact_rows)


def test_regexflag_cached_class_sugar_retains_manager_context_product() -> None:
    graph = DependencyArtifactGraph.authenticate_stdlib_module("re")
    module = graph.modules["re"]
    manager_context = TreeConstructionContextV1.for_source_call_construction()
    foreign_context = TreeConstructionContextV1.for_source_call_construction()
    foreign = SourceFile(
        (module.source, module.source_seat, module.source_cid),
        construction_context=foreign_context,
    )
    manager = SourceFile(
        (module.source, module.source_seat, module.source_cid),
        construction_context=manager_context,
    )

    def regex_flag(source_file: SourceFile) -> ClassDef:
        return next(
            node
            for node in source_file.root.body
            if isinstance(node, ClassDef) and node.name == "RegexFlag"
        )

    foreign_class = regex_flag(foreign)
    foreign_sugar = foreign_class.sugar()
    object.__setattr__(
        manager.unit, "construction_cache", foreign.unit.construction_cache
    )
    manager_class = replace(foreign_class, unit=manager.unit)
    _seat_import_value_use_receipts(
        source_file=manager,
        module=module,
        target=manager_class,
        session=SourceResolutionSession(enabled=False),
        context=manager_context,
        dependency_graphs={"re": graph},
    )
    manager_sugar = manager_class.sugar()
    assert manager_sugar is not foreign_sugar
    manager_sugar = regex_flag(manager).sugar()
    ascii_field = next(field for field in manager_sugar.fields if field.name == "ASCII")
    outcome = ascii_field.value_sugar.desugar()

    assert type(outcome.value) is ImportMemberValue
    assert not foreign_context.source_import_value_receipts_by_site
    assert outcome.value.receipt in manager_context.source_import_value_receipts[
        (module.module_name, module.source_seat, module.source_cid)
    ]


def test_import_receipt_seating_requires_the_target_unit_owned_context() -> None:
    graph = DependencyArtifactGraph.authenticate_stdlib_module("re")
    module = graph.modules["re"]
    owned_context = TreeConstructionContextV1.for_source_call_construction()
    foreign_context = TreeConstructionContextV1.for_source_call_construction()
    source_file = SourceFile(
        (module.source, module.source_seat, module.source_cid),
        construction_context=owned_context,
    )
    regex_flag = next(
        node
        for node in source_file.root.body
        if isinstance(node, ClassDef) and node.name == "RegexFlag"
    )

    with pytest.raises(
        BackendDefect,
        match="target SourceUnit construction context disagrees",
    ):
        _seat_import_value_use_receipts(
            source_file=source_file,
            module=module,
            target=regex_flag,
            session=SourceResolutionSession(enabled=False),
            context=foreign_context,
            dependency_graphs={"re": graph},
        )

    assert not foreign_context.source_import_value_receipts
    assert not foreign_context.source_import_value_receipts_by_site
    assert not owned_context.source_import_value_receipts

    _seat_import_value_use_receipts(
        source_file=source_file,
        module=module,
        target=regex_flag,
        session=SourceResolutionSession(enabled=False),
        context=owned_context,
        dependency_graphs={"re": graph},
    )
    assert owned_context is regex_flag.unit.construction_context
    assert owned_context.source_import_value_receipts
    assert owned_context.source_import_value_receipts_by_site

    member = next(
        node
        for node in source_file.nodes()
        if isinstance(node, Attribute)
        and node.attr == "SRE_FLAG_ASCII"
        and node.line_col_span().start_line == 145
    )
    outcome = member.sugar().desugar()
    roster_key = (module.module_name, module.source_seat, module.source_cid)
    span = member.line_col_span()
    site_key = (
        source_file.unit.filename,
        module.source_cid,
        span.start_line,
        span.start_col,
        span.end_line,
        span.end_col,
    )
    assert type(outcome.value) is ImportMemberValue
    assert outcome.value.receipt is owned_context.source_import_value_receipts_by_site[
        site_key
    ]
    assert outcome.value.receipt in owned_context.source_import_value_receipts[
        roster_key
    ]

    foreign = SourceFile(
        (module.source, module.source_seat, module.source_cid),
        construction_context=foreign_context,
    )
    foreign_member = next(
        node
        for node in foreign.nodes()
        if isinstance(node, Attribute)
        and node.attr == "SRE_FLAG_ASCII"
        and node.line_col_span().start_line == 145
    )
    with pytest.raises(SugarNotWritten, match="SymbolicValue.attribute"):
        foreign_member.sugar().desugar()
