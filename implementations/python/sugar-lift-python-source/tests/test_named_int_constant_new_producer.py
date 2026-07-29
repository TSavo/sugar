"""Authenticated source-visible ``__new__`` producer contract.

This is a consumer-facing instrument for the existing constructor door in
``ClassDef``.  It deliberately uses no new receipt or constructor helper.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.context_manager_resolution import (
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.floor import ObjectValue, StringValue
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.source_call_frame import SourceCallBindingGap
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Call, ClassDef, FunctionDef
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


def _source(source: str) -> tuple[SourceFile, ClassDef, Call]:
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (source, "named_constant.py", blake3_512_of(source.encode("utf-8"))),
        construction_context=context,
    )
    definition = next(node for node in tree.nodes() if isinstance(node, ClassDef))
    call = tuple(node for node in tree.nodes() if isinstance(node, Call))[-1]
    context.source_call_frames[_coordinate(call)] = (
        definition.source_visible_constructor_frame()
    )
    return tree, definition, call


def test_truthful_new_uses_existing_constructor_door_and_preserves_unrelated_field():
    source = (
        "class NamedIntConstant(int):\n"
        "    def __new__(cls, value, label):\n"
        "        self = super(NamedIntConstant, cls).__new__(cls, value)\n"
        "        self.label = label\n"
        "        return self\n"
        "    marker = 'unrelated'\n"
        "\nNamedIntConstant(7, 'seven')\n"
    )
    tree, definition, call = _source(source)
    shape = definition._authenticated_new_constructor_shape()
    assert shape is not None
    assert isinstance(shape[0], FunctionDef)
    outcome = call.sugar().desugar()
    assert isinstance(outcome, Complete)
    receiver = outcome.value.force_floor(
        None, owner="named-int-constant-truthful", project_callsite=False
    )
    assert isinstance(receiver, ObjectValue)
    assert receiver.attribute("label", call.fragment).value == StringValue("seven")
    assert definition.source_visible_constructor_frame().owner is definition


@pytest.mark.parametrize(
    "source",
    [
        "class Named(int):\n    def __new__(other, value, label):\n        return value\n\nNamed(7, 'x')\n",
        "class Named(int):\n    def __new__(cls, value, label):\n        return value\n\nNamed(7, 'x')\n",
        "class Named(int):\n    def __new__(cls, label, value):\n        return value\n\nNamed(7, 'x')\n",
    ],
)
def test_malformed_or_foreign_new_shape_is_loud(source: str):
    _, definition, call = _source(source)
    assert definition._authenticated_new_constructor_shape() is None
    with pytest.raises(SourceCallBindingGap):
        call.sugar()


def test_foreign_new_return_is_bodyless_loud():
    _, definition, call = _source(
        "class Named(int):\n"
        "    def __new__(cls, value, label):\n"
        "        self = super(Named, cls).__new__(cls, value)\n"
        "        self.label = label\n"
        "        return value\n"
        "\nNamed(7, 'x')\n"
    )
    assert definition._authenticated_new_constructor_shape() is None
    with pytest.raises(SourceCallBindingGap):
        call.sugar()


def test_no_new_control_has_no_authenticated_new_shape():
    _, definition, _ = _source(
        "class Plain:\n    marker = 'unrelated'\n\nPlain()\n"
    )
    assert definition._authenticated_new_constructor_shape() is None
