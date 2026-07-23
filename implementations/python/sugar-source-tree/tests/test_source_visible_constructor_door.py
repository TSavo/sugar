from __future__ import annotations

from types import SimpleNamespace

import pytest

from sugar_lift_py_tests.context_manager_resolution import SourceFragmentCoordinateV1
from sugar_lift_py_tests.floor import BlockValue, CallSiteValue, ReturnValue, TermValue
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


def test_parameterized_source_frame_stays_loud_until_binding_coordinate_lands() -> None:
    context = SimpleNamespace(source_call_frames={})
    source = _source_file(
        "def renamed_identity(value):\n" "    return value\n\n" "renamed_identity(7)\n",
        context=context,
    )
    function = next(node for node in source.nodes() if isinstance(node, FunctionDef))
    call = next(node for node in source.nodes() if isinstance(node, Call))
    context.source_call_frames[_coordinate(call)] = function.source_visible_call_frame()

    with pytest.raises(SugarNotWritten, match="awaiting-binding-coordinate"):
        call.sugar().desugar()


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
    with pytest.raises(SugarNotWritten, match="awaiting-binding-coordinate"):
        outcome.value.construct_receiver_state(())


def test_unknown_class_member_stays_typed_loud() -> None:
    source = _source_file("class RenamedGuard:\n    state = make_state()\n")
    class_node = next(node for node in source.nodes() if isinstance(node, ClassDef))

    with pytest.raises(SugarNotWritten, match="unsupported class member Assign"):
        class_node.sugar()
