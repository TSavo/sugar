"""The shadow AST threads the post-state of ``dict.setdefault`` chains."""

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_py_tests.context_manager_resolution import (
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.floor import CallSiteValue, ListValue, StringValue, TermValue
from sugar_lift_py_tests.outcome import Complete
from sugar_source_tree.nodes import (
    Call,
    DictSetDefaultAppendState,
    DictSetDefaultAppendStatement,
    FunctionDef,
)
from sugar_source_tree.tree import SourceFile


def _project_return(source: str):
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (source, "dict_setdefault_fixture.py", blake3_512_of(source.encode())),
        construction_context=context,
    )
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    substituted = function.substitute({})
    assert any(
        isinstance(node, DictSetDefaultAppendStatement)
        for node in substituted.walk()
    )
    assert any(
        isinstance(node, DictSetDefaultAppendState) for node in substituted.walk()
    )
    call = tuple(node for node in tree.nodes() if isinstance(node, Call))[-1]
    span = call.line_col_span()
    coordinate = SourceFragmentCoordinateV1(
        call.unit.source_cid,
        span.start_line,
        span.start_col,
        span.end_line,
        span.end_col,
    )
    context.source_call_frames[coordinate] = function.source_visible_call_frame()
    outcome = call.sugar().desugar(None)
    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, CallSiteValue)
    projected = outcome.value.project_operation_receiver_outcome(
        None, owner="test_dict_setdefault_shadow_state"
    )
    assert isinstance(projected, Complete)
    return projected.value


def test_missing_key_insert_and_append_are_visible_to_later_read() -> None:
    projected = _project_return(
        "def producer():\n"
        "    d = {}\n"
        "    d.setdefault('_ignore_', []).append('_ignore_')\n"
        "    return d['_ignore_']\n\n"
        "producer()\n"
    )
    assert projected == ListValue((StringValue("_ignore_"),))


def test_existing_key_wins_over_default_before_append() -> None:
    projected = _project_return(
        "def producer():\n"
        "    d = {'x': [1]}\n"
        "    d.setdefault('x', [9]).append(2)\n"
        "    return d['x']\n\n"
        "producer()\n"
    )
    assert projected == ListValue((TermValue(1), TermValue(2)))
    assert projected != ListValue((TermValue(9), TermValue(2)))
