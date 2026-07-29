from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.context_manager_resolution import (
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_source_tree.nodes import ClassDef
from sugar_source_tree.tree import SourceFile


def _tree(tmp_path: Path, monkeypatch) -> SourceFile:
    monkeypatch.chdir(tmp_path)
    path = Path("decorated_module.py")
    path.write_text(
        "def replace(raw):\n"
        "    return raw\n"
        "\n"
        "@replace\n"
        "class Original:\n"
        "    token = 7\n"
    )
    return SourceFile.from_path(
        path,
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def test_backend_module_construction_owns_a_stable_receipt_cid(
    tmp_path: Path, monkeypatch
) -> None:
    tree = _tree(tmp_path, monkeypatch)

    receipt = tree.root.unit.constructed_module.construction_event_receipt

    assert receipt.source_cid == tree.root.unit.source_cid
    assert isinstance(receipt.receipt_cid, str)
    assert receipt.receipt_cid


def test_class_definition_carries_ordered_decorator_sugars_and_occurrences(
    tmp_path: Path, monkeypatch
) -> None:
    tree = _tree(tmp_path, monkeypatch)
    definition = next(item for item in tree.root.body if isinstance(item, ClassDef))

    sugar = definition.sugar()

    assert len(sugar.decorator_sugars) == 1
    assert len(sugar.decorator_occurrences) == 1
    occurrence = sugar.decorator_occurrences[0]
    assert type(occurrence) is SourceFragmentCoordinateV1
    assert occurrence.source_cid == tree.root.unit.source_cid
    assert occurrence == SourceFragmentCoordinateV1(
        tree.root.unit.source_cid,
        definition.decorators[0].line_col_span().start_line,
        definition.decorators[0].line_col_span().start_col,
        definition.decorators[0].line_col_span().end_line,
        definition.decorators[0].line_col_span().end_col,
    )
