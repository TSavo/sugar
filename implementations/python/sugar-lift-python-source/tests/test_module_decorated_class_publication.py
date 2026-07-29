from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor.decorated_class_value import (
    DecoratedClassMemberValue,
    DecoratedClassValue,
)
from sugar_lift_py_tests.outcome import Complete
from sugar_source_tree.tree import SourceFile


def test_module_execution_publishes_replacing_decorator_result_and_member(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    path = Path("decorated_module.py")
    path.write_text(
        "class Replacement:\n"
        "    token = 7\n"
        "\n"
        "def replace(raw):\n"
        "    return Replacement\n"
        "\n"
        "def retain(value):\n"
        "    return value\n"
        "\n"
        "@retain\n"
        "@replace\n"
        "class Original:\n"
        "    stale = 1\n"
    )
    tree = SourceFile.from_path(
        path,
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )

    result = tree.root.sugar().desugar()

    assert isinstance(result, Complete)
    publication = result.value.publication_for("Original")
    published = result.value.temporal.value_for("Original")
    member = result.value.temporal.value_for("token")
    assert isinstance(published, DecoratedClassValue)
    assert published.publication is publication
    assert isinstance(member, DecoratedClassMemberValue)
    assert member.publication is publication
    assert tuple(
        application.input_floor for application in publication.decorator_applications
    ) == (publication.raw_class, publication.decorator_applications[0].output_floor)
    assert publication.final_class is published.published_floor
    assert publication.final_class is not publication.raw_class
