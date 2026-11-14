"""``import a.b`` then ``a.b``: the Attribute is the module ``a.b`` (#7712).

The lexical pass enrolls the occurrence ``a.b`` of a submodule binding with an
empty member path (#7626): it names the module itself, not a member of it.
``AttributeSugar`` used to require a member path ending in the Attribute's
name, so this exact, same-source receipt raised a BackendDefect the first time
a lift reduced such a body (``pandas.io.common.urlopen`` under #7709).  The
read completes as the receipt's module coordinate; a receipt that does not
spell this Attribute still refuses.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
from sugar_lift_py_tests.import_binding import authenticated_import_value_use_receipts
from sugar_lift_py_tests.ir import ctor, str_const
from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.attribute_sugar import _submodule_terminus_module
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.nodes import Attribute
from sugar_source_tree.panic import BackendDefect
from sugar_source_tree.tree import SourceFile


def _lexical(tmp_path: Path, text: str):
    path = tmp_path / "m.py"
    path.write_text(text, encoding="utf-8")
    source, _, source_cid = path_source(str(path))
    receipts, _ = authenticated_import_value_use_receipts(
        tmp_path, path, source, source_cid, module_identities={}
    )
    source_file = SourceFile(
        (source, str(path), source_cid),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    return source_file, source_cid, receipts


def _span_key(node):
    span = node.line_col_span()
    return (span.start_line, span.start_col, span.end_line, span.end_col)


def _receipt_at(receipts, key):
    (receipt,) = [
        row
        for row in receipts
        if (
            row.use["useSite"]["startLine"],
            row.use["useSite"]["startCol"],
            row.use["useSite"]["endLine"],
            row.use["useSite"]["endCol"],
        )
        == key
    ]
    return receipt


def test_the_submodule_occurrence_reads_as_its_module(tmp_path):
    source_file, source_cid, receipts = _lexical(
        tmp_path, "def f():\n    import pkg.sub\n    return pkg.sub\n"
    )
    (terminus,) = [
        node
        for node in source_file.nodes()
        if isinstance(node, Attribute) and node.attr == "sub"
    ]
    key = _span_key(terminus)
    receipt = _receipt_at(receipts, key)
    assert receipt.target_symbol == "python:pkg.sub"
    assert list(receipt.use["exportedMemberPath"]) == []
    source_file.unit.seat_import_value_use_resolution(
        key, receipt, source_cid=source_cid
    )

    outcome = terminus.sugar().desugar()

    assert type(outcome) is ExitSet
    value = outcome.completed_value()
    assert type(value) is SymbolicValue
    assert value.term == ctor("python:module", (str_const("pkg.sub"),))


def test_a_receipt_that_does_not_spell_the_attribute_refuses(tmp_path):
    # Lying twin: the same exact module-alias testimony claimed for another
    # name, and a plain ``import pkg`` Name receipt, own no Attribute.
    _file, _cid, receipts = _lexical(
        tmp_path, "import pkg.sub\nimport other\ndef f():\n    return pkg.sub, other\n"
    )
    terminus = next(r for r in receipts if r.target_symbol == "python:pkg.sub")
    alias = next(r for r in receipts if r.target_symbol == "python:other")
    assert _submodule_terminus_module(terminus, "sub") == "pkg.sub"
    assert _submodule_terminus_module(terminus, "other") is None
    assert _submodule_terminus_module(alias, "other") is None


def test_a_crosswired_receipt_at_the_attribute_still_raises(tmp_path):
    # Lying twin through the door: the ``import pkg`` Name receipt carried to
    # the ``pkg.sub`` occurrence is not that occurrence's testimony.
    source_file, source_cid, receipts = _lexical(
        tmp_path, "import pkg\ndef f():\n    return pkg.sub\n"
    )
    (attribute,) = [
        node
        for node in source_file.nodes()
        if isinstance(node, Attribute) and node.attr == "sub"
    ]
    (name_receipt,) = [
        row for row in receipts if row.target_symbol == "python:pkg"
    ]
    context = source_file.unit.construction_context
    span = attribute.line_col_span()
    context.source_import_value_receipts_by_site[
        (
            source_file.unit.filename,
            source_cid,
            span.start_line,
            span.start_col,
            span.end_line,
            span.end_col,
        )
    ] = name_receipt
    with pytest.raises(BackendDefect, match="does not own this Attribute"):
        attribute.sugar().desugar()
