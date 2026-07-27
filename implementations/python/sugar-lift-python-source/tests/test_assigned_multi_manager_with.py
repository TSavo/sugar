from __future__ import annotations

import importlib.metadata
from pathlib import Path

import pytest

from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.manager_summary_derivation import (
    _projected_manager_call_uses,
    populate_source_derived_resource_refs,
)

PANDAS_SOURCE_CID = (
    "blake3-512:60e7b5ba2c971960e4d8edcaa85e916704dc8bfb977bc15dafb2f2b3e87458ff"
    "ba4b2f823e500c4c591a968b7c3e8ed436035aa171e8b3227055d9956147fae1"
)


def _pandas_root() -> Path:
    distribution = importlib.metadata.distribution("pandas")
    package = Path(distribution.locate_file("pandas")).resolve()
    assert distribution.version == "3.0.3"
    assert package.is_dir()
    return package.parent


def _real_tree():
    root = _pandas_root()
    path = root / "pandas/tests/io/formats/test_ipython_compat.py"
    assert path.is_file()
    assert blake3_512_of(path.read_bytes()) == PANDAS_SOURCE_CID
    return open_source_file_for_construction(
        path,
        root=root,
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
        populate_derived=False,
    )


def _line_32_with(tree):
    return next(
        node
        for node in tree.nodes()
        if node.kind == "With" and node.line_col_span().start_line == 32
    )


def test_pandas_303_two_name_managers_project_their_assignment_calls() -> None:
    """The verified corpus site consumes two distinct acquired managers."""
    tree = _real_tree()
    site = _line_32_with(tree)
    assert [item.context_expr.kind for item in site.items] == ["Name", "Name"]

    projected = _projected_manager_call_uses(tree)
    rows = sorted(
        (call.line_col_span().start_line, coordinate.start_line, coordinate.start_col)
        for coordinate, call, _exit_face in projected.values()
        if coordinate.start_line == 32
    )
    assert rows == [(21, 32, 13), (30, 32, 18)]


def test_projection_is_a_transaction_and_does_not_mutate_the_source_tree() -> None:
    tree = _real_tree()
    site = _line_32_with(tree)
    before = tuple(item.context_expr for item in site.items)

    _projected_manager_call_uses(tree)

    assert tuple(item.context_expr for item in site.items) == before
    assert [item.context_expr.kind for item in site.items] == ["Name", "Name"]


def test_pandas_303_assigned_manager_keeps_provider_refusal_loud() -> None:
    """Projection reaches the provider but never invents a resource value."""
    from sugar_lift_py_tests.source_call_frame import SourceCallBindingGap

    tree = _real_tree()
    root = _pandas_root()
    with pytest.raises(SourceCallBindingGap, match="unconsumed call actual"):
        populate_source_derived_resource_refs(
            tree,
            root=root,
            path=root / "pandas/tests/io/formats/test_ipython_compat.py",
        )


def test_undecided_rebinding_does_not_invent_a_second_manager_call(
    tmp_path: Path,
) -> None:
    """Lying twin: the second Name no longer reaches acquired call state."""
    source = tmp_path / "twin.py"
    source.write_text(
        "def exercise(make_manager, undecided):\n"
        "    first = make_manager()\n"
        "    second = make_manager()\n"
        "    second = undecided\n"
        "    with first, second:\n"
        "        pass\n",
        encoding="utf-8",
    )
    tree = open_source_file_for_construction(
        source,
        root=tmp_path,
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
        populate_derived=False,
    )

    projected = _projected_manager_call_uses(tree)
    rows = [
        (coordinate.start_line, coordinate.start_col, call.line_col_span().start_line)
        for coordinate, call, _exit_face in projected.values()
        if coordinate.start_line == 5
    ]
    assert rows == [(5, 9, 2)]
