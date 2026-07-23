"""Starred expression construction mirrors the reference Python lifter."""

import tempfile

import pytest

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.floor import ReturnValue
from sugar_lift_py_tests.outcome import Complete
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _function(source: str):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(source)
        path = f.name
    return next(SourceFile(path_source(path)).functions())


def _returned_term(expression: str):
    out = _function(f"def f(a, b, d):\n    return {expression}\n").sugar().desugar()
    assert isinstance(out, Complete)
    returns = [
        entry
        for entry in out.value.record.statements
        if isinstance(entry, ReturnValue)
    ]
    assert len(returns) == 1
    return returns[0].value.to_term(owner="starred-spread-test")


def test_call_star_and_double_star_use_reference_wrappers() -> None:
    term = _returned_term("make(*a, b, **d)")
    assert term.name == "python:call"
    assert term.args[0].value == "make"
    assert term.args[1].name == "python:starred_arg"
    assert term.args[1].args[0].name == "a"
    assert term.args[2].name == "b"
    assert term.args[3].name == "python:double_starred_kwarg"
    assert term.args[3].args[0].name == "d"


def test_call_with_only_double_star_uses_reference_shape() -> None:
    term = _returned_term("make(**d)")
    assert term.name == "python:call"
    assert len(term.args) == 2
    assert term.args[0].value == "make"
    assert term.args[1].name == "python:double_starred_kwarg"
    assert term.args[1].args[0].name == "d"


@pytest.mark.parametrize(
    ("expression", "outer"),
    [
        ("[*a, *b]", "python:list"),
        ("(*a,)", "python:tuple"),
        ("{*a}", "python:set"),
    ],
)
def test_literal_star_uses_reference_wrapper(expression: str, outer: str) -> None:
    term = _returned_term(expression)
    assert term.name == outer
    assert term.args[0].name == "python:starred"
    assert term.args[0].args[0].name == "a"


def test_dict_double_star_uses_none_key_entry_reference_shape() -> None:
    term = _returned_term("{**d, 'x': a}")
    assert term.name == "python:dict"
    assert term.args[0].name == "python:dict_entry"
    assert term.args[0].args[0].name == "None"
    assert term.args[0].args[1].name == "d"
    assert term.args[1].name == "python:dict_entry"


@pytest.mark.parametrize(
    "body",
    [
        "async def f(xs):\n    return [*(await xs)]\n",
        "async def f(xs):\n    return make(*(await xs))\n",
    ],
)
def test_spread_with_unwritten_inner_expression_stays_loud(body: str) -> None:
    with pytest.raises(SugarNotWritten):
        _function(body).sugar()


def test_starred_assignment_target_remains_a_binding_design_gap() -> None:
    with pytest.raises(SugarNotWritten):
        _function("def f(xs):\n    a, *rest = xs\n    return rest\n").sugar()
