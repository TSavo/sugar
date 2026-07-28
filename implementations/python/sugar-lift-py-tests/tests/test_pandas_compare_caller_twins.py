"""A real pandas Compare pair whose current Floor must stay undischarged."""

from __future__ import annotations

import ast
from dataclasses import dataclass

import pandas as pd
import pandas._testing as tm
import pytest
from pandas import date_range

from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
from sugar_lift_py_tests.floor import CallSiteValue
from sugar_lift_py_tests.ir import ctor

MANIFEST_CID = (
    "blake3-512:6f317a5a489eb7e730064d79792f0d1656723130603309e2f2ed9cbedb604eda"
    "1c4b77a26dc90c980411292ea3994af9015da4cd850b5a307af5a4998b563530"
)
HELPER_PATH = "tests/arithmetic/common.py"
CALLER_PATH = "tests/arithmetic/test_datetime64.py"


@dataclass(frozen=True)
class _Pair:
    helper: ast.FunctionDef
    operation: ast.Compare
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

    helper = _function(ast.parse(helper_source), "assert_invalid_comparison")
    operations = tuple(
        node
        for node in ast.walk(helper)
        if isinstance(node, ast.Compare)
        and isinstance(node.left, ast.Name)
        and len(node.comparators) == 1
        and isinstance(node.comparators[0], ast.Name)
        and (node.left.id, node.comparators[0].id) == ("left", "right")
        and len(node.ops) == 1
        and isinstance(node.ops[0], ast.Lt)
    )
    assert len(operations) == 1
    operation = operations[0]
    assert operation.lineno == 144

    caller_tree = ast.parse(caller_source)
    imports = tuple(
        node
        for node in caller_tree.body
        if isinstance(node, ast.ImportFrom)
        and node.module == "pandas.tests.arithmetic.common"
        and any(alias.name == "assert_invalid_comparison" for alias in node.names)
    )
    assert len(imports) == 1
    assert imports[0].lineno == 35

    caller = _function(caller_tree, "test_dt64arr_cmp_scalar_invalid")
    rendered_decorators = tuple(ast.unparse(item) for item in caller.decorator_list)
    assert any(
        "'foo'" in item and "pytest.mark.parametrize" in item
        for item in rendered_decorators
    )
    assignments = tuple(
        ast.unparse(node)
        for node in caller.body
        if isinstance(node, (ast.Assign, ast.AnnAssign))
    )
    assert "rng = date_range('1/1/2000', periods=10, tz=tz)" in assignments
    assert "dtarr = tm.box_expected(rng, box_with_array)" in assignments
    calls = tuple(
        node
        for node in ast.walk(caller)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "assert_invalid_comparison"
    )
    assert len(calls) == 1
    call = calls[0]
    assert call.lineno == 90
    assert tuple(ast.unparse(argument) for argument in call.args) == (
        "dtarr",
        "other",
        "box_with_array",
    )
    return _Pair(helper, operation, caller, call)


def _actuals():
    """The concrete ``box_with_array=pd.array, other='foo'`` caller arm."""
    rng = date_range("1/1/2000", periods=10)
    return tm.box_expected(rng, pd.array), "foo", pd.array


def test_helper_alone_has_only_formals_so_exception_identity_is_undischarged() -> None:
    """The helper occurrence authenticates an operation, never caller actuals."""
    pair = _pair()

    assert ast.unparse(pair.operation) == "left < right"
    assert tuple(argument.arg for argument in pair.helper.args.args[:2]) == (
        "left",
        "right",
    )
    assert all(
        isinstance(operand, ast.Name)
        for operand in (pair.operation.left, pair.operation.comparators[0])
    )


def test_real_caller_runtime_actuals_raise_but_do_not_supply_floor_testimony() -> None:
    """Runtime establishes TypeError; the boundary expectation does not."""
    _pair()
    left, right, box = _actuals()

    with pytest.raises(TypeError) as raised:
        left < right

    assert type(raised.value) is TypeError
    assert type(raised.value).__module__ == "builtins"
    from pandas.tests.arithmetic.common import assert_invalid_comparison

    assert assert_invalid_comparison(left, right, box) is None


def test_bodyless_call_remains_opaque_without_borrowing_ordering_testimony() -> None:
    """A bodyless call is the negative twin, not a label for the real caller."""
    opaque = CallSiteValue("opaque", (), (), ctor("call:opaque", []), None)

    assert "less_than" not in CallSiteValue.__dict__
    assert opaque._dig_floor_or_none(None, owner="opaque compare twin") is None


def test_lying_caller_coordinate_is_rejected_before_it_can_be_evidence() -> None:
    """Mutation tooth: a nearby but reversed helper call is not this pair."""
    corpus = authenticated_pandas_corpus()
    caller = (corpus.root / CALLER_PATH).read_text(encoding="utf-8")
    lying = caller.replace(
        "assert_invalid_comparison(dtarr, other, box_with_array)",
        "assert_invalid_comparison(other, dtarr, box_with_array)",
        1,
    )

    with pytest.raises(AssertionError):
        _pair(caller_source=lying)
