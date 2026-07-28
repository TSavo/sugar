"""Corpus teeth for discharging a formal BinOp at a real pandas caller."""

from __future__ import annotations

import ast
from dataclasses import dataclass

import pandas as pd
import pandas._testing as tm
import pytest
from pandas import Series, Timedelta

from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
from sugar_lift_py_tests.floor import CallSiteValue, StringValue
from sugar_lift_py_tests.ir import ctor
from sugar_lift_py_tests.outcome.exit_set import Completed, Halted

MANIFEST_CID = (
    "blake3-512:6f317a5a489eb7e730064d79792f0d1656723130603309e2f2ed9cbedb604eda"
    "1c4b77a26dc90c980411292ea3994af9015da4cd850b5a307af5a4998b563530"
)
HELPER_PATH = "tests/arithmetic/common.py"
CALLER_PATH = "tests/arithmetic/test_timedelta64.py"


@dataclass(frozen=True)
class _Pair:
    helper: ast.FunctionDef
    operation: ast.BinOp
    caller: ast.FunctionDef
    call: ast.Call


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    matches = tuple(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == name
    )
    assert len(matches) == 1
    return matches[0]


def _pair(
    *, helper_source: str | None = None, caller_source: str | None = None
) -> _Pair:
    corpus = authenticated_pandas_corpus()
    assert (corpus.version, corpus.file_count, corpus.manifest_cid) == (
        "3.0.3",
        1421,
        MANIFEST_CID,
    )
    helper_source = (
        (corpus.root / HELPER_PATH).read_text(encoding="utf-8")
        if helper_source is None
        else helper_source
    )
    caller_source = (
        (corpus.root / CALLER_PATH).read_text(encoding="utf-8")
        if caller_source is None
        else caller_source
    )

    helper = _function(ast.parse(helper_source), "assert_invalid_addsub_type")
    operations = tuple(
        node
        for node in ast.walk(helper)
        if isinstance(node, ast.BinOp)
        and isinstance(node.left, ast.Name)
        and isinstance(node.right, ast.Name)
        and (node.left.id, node.right.id) == ("left", "right")
        and isinstance(node.op, ast.Add)
    )
    assert len(operations) == 1
    operation = operations[0]
    assert operation.lineno == 55

    caller_tree = ast.parse(caller_source)
    imports = tuple(
        node
        for node in caller_tree.body
        if isinstance(node, ast.ImportFrom)
        and node.module == "pandas.tests.arithmetic.common"
        and any(alias.name == "assert_invalid_addsub_type" for alias in node.names)
    )
    assert len(imports) == 1
    assert imports[0].lineno == 31

    caller = _function(caller_tree, "test_td64arr_addsub_numeric_scalar_invalid")
    rendered_decorators = tuple(ast.unparse(item) for item in caller.decorator_list)
    assert any(
        "pytest.mark.parametrize('other', ['a', 1, 1.5, np.array(2)])" == item
        for item in rendered_decorators
    )
    assignments = tuple(
        ast.unparse(node)
        for node in caller.body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
    )
    assert any(
        "tdser = Series(['59 Days', '59 Days', 'NaT'], dtype='m8[ns]')" == assignment
        for assignment in assignments
    )
    calls = tuple(
        node
        for node in ast.walk(caller)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "assert_invalid_addsub_type"
    )
    assert len(calls) == 1
    call = calls[0]
    assert call.lineno == 1172
    assert tuple(ast.unparse(arg) for arg in call.args) == ("tdarr", "other")
    return _Pair(helper, operation, caller, call)


def _actuals():
    """The concrete ``box_with_array=pd.array, other='a'`` caller arm."""
    tdser = Series(["59 Days", "59 Days", "NaT"], dtype="m8[ns]")
    return tm.box_expected(tdser, pd.array), "a"


def test_helper_alone_has_only_formals_so_exception_identity_is_undischarged() -> None:
    """The helper occurrence authenticates an operation, never caller actuals."""
    pair = _pair()

    assert ast.unparse(pair.operation) == "left + right"
    assert tuple(argument.arg for argument in pair.helper.args.args[:2]) == (
        "left",
        "right",
    )
    assert all(
        isinstance(operand, ast.Name)
        for operand in (pair.operation.left, pair.operation.right)
    )


def test_runtime_truth_names_the_candidate_exception_without_licensing_floor() -> None:
    """Runtime identifies TypeError; this alone cannot authenticate the Floor."""
    _pair()
    left, right = _actuals()

    with pytest.raises(TypeError) as raised:
        left + right

    assert type(raised.value) is TypeError
    assert type(raised.value).__module__ == "builtins"
    # The real helper consumes the same operation at the real caller arm.
    from pandas.tests.arithmetic.common import assert_invalid_addsub_type

    assert assert_invalid_addsub_type(left, right) is None


def test_candidate_pair_existing_floor_remains_undischarged() -> None:
    """The current call-result floor cannot authenticate TimedeltaArray + str.

    Caller substitution constructs ``tdarr`` through ``tm.box_expected``.  Its
    current Floor category is therefore a call result, not a source-decided
    TimedeltaArray.  The binary law conserves both runtime faces, but its halt
    has no exception-type coordinate.  #6588 classifies exactly this shape as
    Undischarged; borrowing ``pytest.raises(TypeError)`` would fabricate it.
    """
    pair = _pair()
    left = CallSiteValue(
        "tm.box_expected",
        (),
        (),
        ctor("call:tm.box_expected", []),
        None,
    )

    outcome = left.add(StringValue("a"), f"{HELPER_PATH}:{pair.operation.lineno}")

    halted = tuple(exit_ for exit_ in outcome.exits if isinstance(exit_, Halted))
    completed = tuple(exit_ for exit_ in outcome.exits if isinstance(exit_, Completed))
    assert len(halted) == 1
    assert len(completed) == 1
    assert halted[0].effect.exception_type_coordinate is None


def test_runtime_wrong_expected_type_does_not_consume_candidate_exception() -> None:
    """At runtime a ValueError boundary leaves the candidate TypeError outside."""
    _pair()
    left, right = _actuals()

    with pytest.raises(TypeError) as escaped:
        with pytest.raises(ValueError):
            left + right

    assert type(escaped.value) is TypeError


def test_runtime_candidate_completes_for_normal_actuals() -> None:
    """Runtime completion is a candidate twin, not authenticated Floor proof."""
    pair = _pair()
    left, _ = _actuals()

    result = left + Timedelta("1D")

    assert ast.unparse(pair.operation) == "left + right"
    assert result.dtype == left.dtype
    assert result[0] == Timedelta("60D")


def test_lying_caller_coordinate_is_rejected_before_it_can_be_evidence() -> None:
    """Mutation tooth: a nearby but different helper call is not this pair."""
    corpus = authenticated_pandas_corpus()
    caller = (corpus.root / CALLER_PATH).read_text(encoding="utf-8")
    lying = caller.replace(
        "assert_invalid_addsub_type(tdarr, other)",
        "assert_invalid_addsub_type(other, tdarr)",
        1,
    )

    with pytest.raises(AssertionError):
        _pair(caller_source=lying)
