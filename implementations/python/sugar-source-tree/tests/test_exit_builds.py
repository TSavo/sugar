"""Plain Return/Raise nodes build the values carried by their exits."""

from __future__ import annotations

import tempfile

import pytest

from sugar_lift_py_tests.floor import NoneValue, ReturnValue
from sugar_lift_py_tests.outcome import Complete, Incomplete
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _function(source: str):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(source)
        path = f.name
    return next(SourceFile(path_source(path)).functions())


def _statement(source: str, kind: str):
    function = _function(source).substitute({})
    return next(node for node in function.walk() if node.kind == kind)


def test_bare_return_builds_the_language_none_exit() -> None:
    outcome = _statement("def A():\n    return\n", "Return").sugar().desugar()

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, ReturnValue)
    assert isinstance(outcome.value.value, NoneValue)


def test_valued_return_carries_its_built_child() -> None:
    outcome = _statement("def A():\n    return 7\n", "Return").sugar().desugar()

    assert isinstance(outcome, Complete)
    assert outcome.value.value.value == 7


def test_implicit_falloff_builds_the_same_none_post() -> None:
    universe = _function("def A():\n    pass\n").sugar().desugar().value

    assert universe.post().args[1].name == "None"


def test_raise_name_points_at_the_built_value() -> None:
    outcome = _statement("def A(exc):\n    raise exc\n", "Raise").sugar().desugar()

    assert isinstance(outcome, Incomplete)
    assert outcome.effect.exception_name == "exc"
    assert outcome.effect.raised_value.to_term(owner="test").name == "exc"


def test_raise_constructor_carries_its_built_call_coordinate() -> None:
    outcome = _statement(
        "def A():\n    raise ValueError(7)\n", "Raise"
    ).sugar().desugar()

    assert isinstance(outcome, Incomplete)
    raised = outcome.effect.raised_value
    assert raised.term.name == "call:ValueError"
    assert raised.term.args[0].value == 7
    assert raised.body is None


def test_unwritten_raised_child_stays_loud() -> None:
    with pytest.raises(SugarNotWritten):
        _statement("def A():\n    raise (lambda: 1)\n", "Raise").sugar()


def test_raise_from_carries_the_built_cause() -> None:
    outcome = _statement(
        "def A():\n    raise ValueError from KeyError\n", "Raise"
    ).sugar().desugar()

    assert isinstance(outcome, Incomplete)
    assert outcome.effect.cause_value.to_term(owner="raise-cause").name == "KeyError"
