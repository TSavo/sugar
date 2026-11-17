"""Starred expression construction mirrors the reference Python lifter."""

import tempfile

import pytest

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.floor import ReturnValue
from sugar_source_tree.panic import SugarNotWritten
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.tree import SourceFile


def _function(source: str):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(source)
        path = f.name
    return next(SourceFile(path_source(path), construction_context=TreeConstructionContextV1.for_test_without_workspace()).functions())


def _returned_term(expression: str):
    out = _function(f"def f(a, b, d):\n    return {expression}\n").sugar().desugar()
    value = out.completed_value()
    assert value is not None
    return _the_return(value)


def _the_return(value):
    returns = [
        entry for entry in value.record.statements if isinstance(entry, ReturnValue)
    ]
    assert len(returns) == 1
    return returns[0].value.to_term(owner="starred-spread-test")


def _returned_call(expression: str):
    """The call term a call to ``make`` returns.  ``make`` may be bound only by
    a star import the lifter cannot read (a name nothing binds is a NameError
    halt), so the call is the unanswered call's two faces: it completes only
    under its completes atom, as ``python:call_result(<call term>, ...)``,
    its halt kept beside it."""
    from sugar_lift_py_tests.outcome import Completed

    out = _function(
        "from unread_module import *\n\n\n"
        f"def f(a, b, d):\n    return {expression}\n"
    ).sugar().desugar()
    assert out.halts(), out.exits
    completed = [e for e in out.normalize().exits if isinstance(e, Completed)]
    assert len(completed) == 1, out.exits
    result = _the_return(completed[0].value)
    assert result.name == "python:call_result", result
    return result.args[0]


def test_call_star_and_double_star_use_reference_wrappers() -> None:
    term = _returned_call("make(*a, b, **d)")
    assert term.name == "python:call"
    assert term.args[0].value == "make"
    assert term.args[1].name == "python:starred_arg"
    assert term.args[1].args[0].name == "a"
    assert term.args[2].name == "b"
    assert term.args[3].name == "python:double_starred_kwarg"
    assert term.args[3].args[0].name == "d"


def test_call_with_only_double_star_uses_reference_shape() -> None:
    term = _returned_call("make(**d)")
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
def test_spread_with_unwritten_inner_expression_stays_loud(
    body: str, monkeypatch
) -> None:
    # Every expression node constructs its sugar now (``Await`` too); the
    # unwritten node is planted by giving ``Await`` back the abstract door
    # every unwritten node inherits (``Node._construct_sugar``).
    from sugar_source_tree.nodes import Await, Node

    monkeypatch.setattr(Await, "_construct_sugar", Node._construct_sugar)
    with pytest.raises(SugarNotWritten):
        _function(body).sugar()


def test_starred_assignment_target_binds_and_keeps_its_arity_halt() -> None:
    """``a, *rest = xs`` is built: the starred target binds the remainder,
    and the unpack over a formal keeps its own undetermined halt (too few
    items) beside the completed face -- never a completion alone."""
    from sugar_lift_py_tests.effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.outcome import Completed

    out = _function("def f(xs):\n    a, *rest = xs\n    return rest\n").sugar().desugar()
    assert any(isinstance(e, Completed) for e in out.exits), out.exits
    assert any(
        isinstance(halt.effect, UndeterminedRaiseEffect) for halt in out.halts()
    ), out.exits
