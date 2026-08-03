from __future__ import annotations

from dataclasses import replace

import pytest

from sugar_lift_py_tests.floor import TermValue, TupleValue
from sugar_lift_py_tests.source_call_frame import SourceCallBindingGap
from sugar_source_tree.nodes import ClassDef
from sugar_source_tree.tree import SourceFile


def test_source_call_frame_rejects_same_source_foreign_definition_site(
    tmp_path,
) -> None:
    path = tmp_path / "two_frames.py"
    path.write_text(
        "def left(value):\n"
        "    return value\n"
        "\n"
        "def right(value):\n"
        "    return value\n",
        encoding="utf-8",
    )
    functions = {
        function.name: function for function in SourceFile.from_path(path).functions()
    }
    left = functions["left"].source_visible_call_frame()
    right = functions["right"].source_visible_call_frame()
    actual = TermValue(7)

    truthful = left.bind_actuals((actual,), ())
    assert truthful.actuals == (actual,)

    wrong_site = replace(left, definition_site=right.definition_site)
    with pytest.raises(SourceCallBindingGap, match="definition site"):
        wrong_site.bind_actuals((actual,), ())


def test_class_constructor_binds_its_initializer_parameter_roster(tmp_path) -> None:
    path = tmp_path / "class_frame.py"
    path.write_text(
        "class Box:\n"
        "    def __init__(self, value):\n"
        "        self.value = value\n",
        encoding="utf-8",
    )
    source = SourceFile.from_path(path)
    class_node = next(node for node in source.nodes() if isinstance(node, ClassDef))
    frame = class_node.source_visible_constructor_frame()
    actual = TermValue(11)

    bound = frame.bind_actuals((actual,), ())

    assert frame.parameters == ("value",)
    assert bound.actuals == (actual,)
    assert frame.formal_declaration_sites == tuple(
        coordinate.binding_site for coordinate in frame.formal_coordinates
    )


def test_class_constructor_rejects_same_arity_foreign_initializer_roster(
    tmp_path,
) -> None:
    path = tmp_path / "foreign_initializer.py"
    path.write_text(
        "class Left:\n"
        "    def __init__(self, value):\n"
        "        self.value = value\n\n"
        "class Right:\n"
        "    def __init__(self, value):\n"
        "        self.value = value\n",
        encoding="utf-8",
    )
    source = SourceFile.from_path(path)
    classes = {node.name: node for node in source.nodes() if isinstance(node, ClassDef)}
    left = classes["Left"].source_visible_constructor_frame()
    right = classes["Right"].source_visible_constructor_frame()
    wrong_roster = replace(
        left, formal_declaration_sites=right.formal_declaration_sites
    )

    with pytest.raises(SourceCallBindingGap, match="foreign declaration site"):
        wrong_roster.bind_actuals((TermValue(11),), ())


def test_inherited_exception_constructor_retains_vararg_roster(tmp_path) -> None:
    path = tmp_path / "exception_frame.py"
    path.write_text("class Raised(Exception):\n    pass\n", encoding="utf-8")
    source = SourceFile.from_path(path)
    class_node = next(node for node in source.nodes() if isinstance(node, ClassDef))
    frame = class_node.source_visible_constructor_frame()
    left = TermValue(1)
    right = TermValue(2)

    bound = frame.bind_actuals((left, right), ())

    assert frame.parameters == ("args",)
    assert bound.actuals == (TupleValue((left, right)),)
