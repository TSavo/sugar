from __future__ import annotations

from dataclasses import replace

import pytest

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.panic import BackendDefect
from sugar_source_tree.spans import LineColSpan
from sugar_source_tree.tree import SourceFile


def _file(source: str, filename: str = "backend-lexical-rows.py") -> SourceFile:
    return SourceFile((source, filename, blake3_512_of(source.encode())))


def test_materialization_walk_emits_exact_parent_child_and_shadow_rows() -> None:
    source_file = _file(
        "def child(value):\n"
        "    return value + 100\n\n"
        "outer_result = child(2)\n\n"
        "def parent():\n"
        "    def child(value):\n"
        "        return value + 1\n"
        "    return child(3)\n"
    )
    product = source_file.unit.backend_materialization_traversal
    outer_row, nested_row = product.lexical_call_rows

    assert outer_row.source_cid == nested_row.source_cid
    assert outer_row.definition is not nested_row.definition
    assert (
        outer_row.function_definition_identity
        != nested_row.function_definition_identity
    )
    assert nested_row.lexical_parent_identity == nested_row.lexical_scope_identity
    assert outer_row.definition_locus == LineColSpan(1, 0, 2, 22)
    assert outer_row.call_locus == LineColSpan(4, 15, 4, 23)
    assert nested_row.definition_locus == LineColSpan(7, 4, 8, 24)
    assert nested_row.call_locus == LineColSpan(9, 11, 9, 19)


def test_materialization_row_rejects_wrong_definition_call_and_scope_twins() -> None:
    source_file = _file(
        "def first_parent():\n"
        "    def child(value):\n"
        "        return value + 1\n"
        "    first = child(3)\n"
        "    return first\n\n"
        "def second_parent():\n"
        "    def child(value):\n"
        "        return value + 2\n"
        "    return child(4)\n"
    )
    product = source_file.unit.backend_materialization_traversal
    first_row, second_row = product.lexical_call_rows

    with pytest.raises(BackendDefect, match="exact FunctionDef identity"):
        replace(first_row, definition=second_row.definition)
    with pytest.raises(BackendDefect, match="exact call occurrence"):
        replace(first_row, call=second_row.call)
    with pytest.raises(BackendDefect, match="lexical scope identity"):
        replace(first_row, lexical_scope_identity=second_row.lexical_scope_identity)


def test_materialization_row_rejects_foreign_same_signature_frame() -> None:
    source_file = _file(
        "def parent():\n"
        "    def child(value):\n"
        "        return value + 1\n"
        "    return child(3)\n"
    )
    foreign_file = _file(
        "def parent():\n"
        "    def child(value):\n"
        "        return value + 2\n"
        "    return child(3)\n",
        filename="foreign-backend-lexical-rows.py",
    )
    source_product = source_file.unit.backend_materialization_traversal
    foreign_product = foreign_file.unit.backend_materialization_traversal
    (row,) = source_product.lexical_call_rows
    (foreign_row,) = foreign_product.lexical_call_rows

    assert row.source_cid != foreign_row.source_cid

    with pytest.raises(BackendDefect, match="source CID"):
        replace(row, definition=foreign_row.definition)


def test_materialization_row_rejects_same_source_wrong_exact_definition() -> None:
    source_file = _file(
        "def sibling(value):\n"
        "    return value + 2\n\n"
        "sibling_result = sibling(2)\n\n"
        "def parent():\n"
        "    def child(value):\n"
        "        return value + 1\n"
        "    return child(3)\n"
    )
    product = source_file.unit.backend_materialization_traversal
    sibling_row, nested_row = product.lexical_call_rows

    assert sibling_row.source_cid == nested_row.source_cid
    with pytest.raises(BackendDefect, match="exact FunctionDef identity"):
        replace(nested_row, definition=sibling_row.definition)
