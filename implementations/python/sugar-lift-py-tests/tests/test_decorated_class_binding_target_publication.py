"""Exact ClassDef binding-target authority for decorated publication."""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.context_manager_resolution import SourceFragmentCoordinateV1
from sugar_lift_py_tests.floor import ClassDefinitionValue, SymbolicValue
from sugar_lift_py_tests.floor.decorated_class_value import (
    DecoratedClassPublicationV1,
    DecoratedClassValue,
    DecoratorApplicationPublicationV1,
)
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.source_call_frame import (
    DecoratedClassBindingV1,
    SourceCallBindingGap,
)
from sugar_source_tree.nodes import ClassDef
from sugar_source_tree.tree import SourceFile


def _coordinate(node) -> SourceFragmentCoordinateV1:
    span = node.line_col_span()
    return SourceFragmentCoordinateV1(
        node.unit.source_cid,
        span.start_line,
        span.start_col,
        span.end_line,
        span.end_col,
    )


def _class_value(definition: ClassDef) -> ClassDefinitionValue:
    outcome = definition.sugar().desugar(
        ReduceContext.root(owner="decorated binding target test")
    )
    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, ClassDefinitionValue)
    return outcome.value


def _classes(tmp_path: Path):
    path = tmp_path / "decorated_binding.py"
    path.write_text(
        "class Replacement:\n"
        "    token = 7\n"
        "\n"
        "class Original:\n"
        "    stale = 1\n"
        "\n"
        "class Original:\n"
        "    foreign = 2\n",
        encoding="utf-8",
    )
    tree = SourceFile.from_path(path)
    definitions = tuple(item for item in tree.root.body if isinstance(item, ClassDef))
    replacement, original, same_name_foreign = definitions
    raw = _class_value(original)
    final = _class_value(replacement)
    application = DecoratorApplicationPublicationV1.mint(
        occurrence=_coordinate(original),
        callable_floor=SymbolicValue(make_var("replace")),
        input_floor=raw,
        output_floor=final,
    )
    return tree, replacement, original, same_name_foreign, raw, final, application


def _publication(
    tree,
    original,
    raw,
    final,
    application,
    *,
    binding_occurrence=None,
    final_class=None,
):
    return DecoratedClassPublicationV1.mint(
        source_cid=tree.root.unit.source_cid,
        definition=_coordinate(original),
        binding_occurrence=(
            _coordinate(original.binding_target)
            if binding_occurrence is None
            else binding_occurrence
        ),
        raw_class=raw,
        decorator_applications=(application,),
        final_class=final if final_class is None else final_class,
        module_construction_receipt_cid="blake3-512:" + "42" * 64,
    )


def test_publication_connects_exact_class_binding_target_to_replacement_fields(
    tmp_path: Path,
) -> None:
    tree, _, original, _, raw, final, application = _classes(tmp_path)

    publication = _publication(tree, original, raw, final, application)
    binding = DecoratedClassBindingV1(
        "Original", publication, DecoratedClassValue(publication)
    )

    assert publication.definition == _coordinate(original)
    assert publication.binding_occurrence == _coordinate(original.binding_target)
    assert binding.publication is publication
    assert binding.value.published_floor is final
    assert {field.name for field in final.class_fields} == {"token"}
    assert "stale" not in {field.name for field in final.class_fields}
    assert {field.name for field in raw.class_fields} == {"stale"}


def test_same_name_binding_target_from_same_source_cannot_substitute(
    tmp_path: Path,
) -> None:
    tree, _, original, same_name_foreign, raw, final, application = _classes(tmp_path)

    with pytest.raises(ValueError, match="binding target"):
        _publication(
            tree,
            original,
            raw,
            final,
            application,
            binding_occurrence=_coordinate(same_name_foreign.binding_target),
        )


def test_same_definition_different_header_token_cannot_substitute(
    tmp_path: Path,
) -> None:
    tree, _, original, _, raw, final, application = _classes(tmp_path)
    definition = _coordinate(original)
    class_keyword = SourceFragmentCoordinateV1(
        definition.source_cid,
        definition.start_line,
        definition.start_col,
        definition.start_line,
        definition.start_col + len("class"),
    )

    with pytest.raises(ValueError, match="binding target"):
        _publication(
            tree,
            original,
            raw,
            final,
            application,
            binding_occurrence=class_keyword,
        )


def test_foreign_source_binding_target_cannot_substitute(tmp_path: Path) -> None:
    tree, _, original, _, raw, final, application = _classes(tmp_path)
    foreign_path = tmp_path / "foreign.py"
    foreign_path.write_text("class Original:\n    stale = 1\n", encoding="utf-8")
    foreign = next(
        item
        for item in SourceFile.from_path(foreign_path).root.body
        if isinstance(item, ClassDef)
    )

    with pytest.raises(ValueError, match="source coordinate mismatch"):
        _publication(
            tree,
            original,
            raw,
            final,
            application,
            binding_occurrence=_coordinate(foreign.binding_target),
        )


def test_class_definition_value_refuses_missing_or_wrong_binding_authority() -> None:
    with pytest.raises(TypeError):
        ClassDefinitionValue("Original", "class-cid", (), None)  # type: ignore[call-arg]

    with pytest.raises(TypeError, match="exact SourceFragmentCoordinateV1"):
        ClassDefinitionValue(
            "Original",
            "class-cid",
            (),
            None,
            object(),  # type: ignore[arg-type]
        )


def test_raw_class_definition_cannot_substitute_after_replacement(
    tmp_path: Path,
) -> None:
    tree, _, original, _, raw, final, application = _classes(tmp_path)
    publication = _publication(tree, original, raw, final, application)

    with pytest.raises(ValueError, match="final result mismatch"):
        _publication(
            tree,
            original,
            raw,
            final,
            application,
            final_class=raw,
        )
    with pytest.raises(SourceCallBindingGap, match="exact publication testimony"):
        DecoratedClassBindingV1("Original", publication, raw)
