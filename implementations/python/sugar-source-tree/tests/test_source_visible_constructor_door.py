from __future__ import annotations

from types import SimpleNamespace

import pytest

from sugar_lift_py_tests.context_manager_resolution import SourceFragmentCoordinateV1
from sugar_lift_py_tests.floor import (
    BlockValue,
    CallSiteValue,
    DictValue,
    ReturnValue,
    StringValue,
    TermValue,
    TupleValue,
)
from sugar_lift_py_tests.outcome import Complete
from sugar_source_tree.nodes import Call, ClassDef, FunctionDef
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _source_file(source: str, *, context=None) -> SourceFile:
    from sugar_lift_python_source.canonical import blake3_512_of

    return SourceFile(
        (source, "renamed_fixture.py", blake3_512_of(source.encode("utf-8"))),
        construction_context=context,
    )


def _coordinate(node) -> SourceFragmentCoordinateV1:
    span = node.line_col_span()
    return SourceFragmentCoordinateV1(
        node.unit.source_cid,
        span.start_line,
        span.start_col,
        span.end_line,
        span.end_col,
    )


def test_source_visible_zero_parameter_call_carries_the_ordinary_body() -> None:
    context = SimpleNamespace(source_call_frames={})
    source = _source_file(
        "def renamed_value():\n" "    return 7\n\n" "renamed_value()\n",
        context=context,
    )
    function = next(node for node in source.nodes() if isinstance(node, FunctionDef))
    call = next(node for node in source.nodes() if isinstance(node, Call))
    frame = function.source_visible_call_frame()
    context.source_call_frames[_coordinate(call)] = frame

    outcome = call.sugar().desugar()

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, CallSiteValue)
    assert outcome.value.body is frame.body
    assert outcome.value.parameters == ()
    assert frame.frame_cid.startswith("blake3-512:")
    constructed = outcome.value.force_floor(
        None, owner="source-visible-call-frame", project_callsite=False
    )
    assert isinstance(constructed, BlockValue)
    assert len(constructed.statements) == 1
    assert isinstance(constructed.statements[0], ReturnValue)
    assert constructed.statements[0].value == TermValue(7)


def test_parameterized_source_frame_projects_the_exact_actual_by_coordinate() -> None:
    context = SimpleNamespace(source_call_frames={})
    source = _source_file(
        "def renamed_identity(value):\n" "    return value\n\n" "renamed_identity(7)\n",
        context=context,
    )
    function = next(node for node in source.nodes() if isinstance(node, FunctionDef))
    call = next(node for node in source.nodes() if isinstance(node, Call))
    context.source_call_frames[_coordinate(call)] = function.source_visible_call_frame()

    frame = function.source_visible_call_frame()
    context.source_call_frames[_coordinate(call)] = frame

    outcome = call.sugar().desugar()

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, CallSiteValue)
    assert len(frame.formal_coordinates) == 1
    assert frame.formal_coordinates[0].projection_path == ("formal", 0)
    constructed = outcome.value.force_floor(
        None, owner="coordinate-source-visible-call-frame", project_callsite=False
    )
    assert isinstance(constructed, BlockValue)
    assert isinstance(constructed.statements[0], ReturnValue)
    assert constructed.statements[0].value == TermValue(7)


def test_class_definition_constructs_methods_but_receiver_state_awaits_coordinate() -> (
    None
):
    source = _source_file(
        "class RenamedGuard:\n"
        "    def __init__(self, expected):\n"
        "        self.expected = expected\n\n"
        "    def enter(self):\n"
        "        return self\n"
    )
    class_node = next(node for node in source.nodes() if isinstance(node, ClassDef))

    outcome = class_node.sugar().desugar()

    assert isinstance(outcome, Complete)
    assert outcome.value.class_name == "RenamedGuard"
    assert tuple(method.name for method in outcome.value.methods) == (
        "__init__",
        "enter",
    )
    assert outcome.value.initializer is not None
    assert outcome.value.class_definition_cid.startswith("blake3-512:")
    receiver = outcome.value.construct_receiver_state((TermValue(11),))

    assert receiver.class_name == "RenamedGuard"
    assert {field.name: field.value for field in receiver.fields} == {
        "expected": TermValue(11)
    }
    assert receiver.identity.startswith("blake3-512:")


def test_source_frame_binds_constructed_defaults_and_variadics() -> None:
    context = SimpleNamespace(source_call_frames={})
    source = _source_file(
        "def renamed_default(value=9):\n"
        "    return value\n\n"
        "def renamed_variadic(first, *rest, **options):\n"
        "    return rest\n\n"
        "renamed_default()\n"
        "renamed_variadic(1, 2, 3, label=4)\n",
        context=context,
    )
    functions = {
        node.name: node for node in source.nodes() if isinstance(node, FunctionDef)
    }
    calls = [node for node in source.nodes() if isinstance(node, Call)]
    context.source_call_frames[_coordinate(calls[0])] = functions[
        "renamed_default"
    ].source_visible_call_frame()
    context.source_call_frames[_coordinate(calls[1])] = functions[
        "renamed_variadic"
    ].source_visible_call_frame()

    default_call = calls[0].sugar().desugar().value
    default_block = default_call.force_floor(
        None, owner="default-call-frame", project_callsite=False
    )
    assert default_block.statements[0].value == TermValue(9)

    variadic_call = calls[1].sugar().desugar().value
    assert isinstance(variadic_call.arg_values[1], TupleValue)
    assert variadic_call.arg_values[1].elements == (TermValue(2), TermValue(3))
    assert isinstance(variadic_call.arg_values[2], DictValue)
    assert variadic_call.arg_values[2].entries == (
        (StringValue("label"), TermValue(4)),
    )


def test_unknown_class_member_stays_typed_loud() -> None:
    source = _source_file("class RenamedGuard:\n    state = make_state()\n")
    class_node = next(node for node in source.nodes() if isinstance(node, ClassDef))

    with pytest.raises(SugarNotWritten, match="unsupported class member Assign"):
        class_node.sugar()
