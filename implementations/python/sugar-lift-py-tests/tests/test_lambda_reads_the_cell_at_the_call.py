"""A lambda reads an enclosing local's cell when it is called (#7757 item 7,
found by #7958).

``x = 1; f = lambda: x; x = 2; f()`` returns 2: Python reads the enclosing
cell when the lambda runs.  The lambda's body used to read the binding it was
created under.  It now reads each enclosing local through a captured
coordinate (``Lambda._captured_bindings``), as a nested ``def`` does
(``FunctionDef._captured_bindings``), and a call carries the binding its own
scope holds for the name at the call (``Call._closure_cells``), bound under
that coordinate before the body runs (``ComputedCallSugar.captured``,
``with_captured_values``).  A lambda passed on, where the binding at its
call is not known, is refused by name
(``LambdaCallable.callable_application_with``).

A lambda an eager comprehension stores still reads the comprehension's final
member (#7944, #7949): that is the comprehension cell's value at the call.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import CallSiteValue, LambdaCallable, TermValue
from sugar_lift_py_tests.floor.guarded_return import GuardedReturn
from sugar_lift_py_tests.floor.return_value import ReturnValue
from sugar_lift_py_tests.outcome import Completed, outcome_to_exitset
from sugar_lift_py_tests.sugar.computed_call_sugar import ComputedCallSugar
from sugar_lift_py_tests.temporal.temporal_context import projection_key
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.nodes import (
    Assign,
    BindingCoordinateRef,
    Call,
    EvaluationRef,
    FunctionDef,
    Lambda,
    ListComp,
    Return,
    final_member_coordinate,
)
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile

ONE, TWO = TermValue(1), TermValue(2)

# The rebind comes between the lambda and its call: the call reads 2.
CALLED_AFTER_REBIND = (
    "def f():\n"
    "    x = 1\n"
    "    g = lambda: x\n"
    "    x = 2\n"
    "    return g()\n"
)
# The call comes before the rebind: it reads 1.
CALLED_BEFORE_REBIND = (
    "def f():\n"
    "    x = 1\n"
    "    g = lambda: x\n"
    "    r = g()\n"
    "    x = 2\n"
    "    return r\n"
)
# The lambda escapes: whoever calls it, its enclosing binding then is unknown.
PASSED_ON = "def f():\n    x = 1\n    return lambda v: v + x\n"
# An eager comprehension stores the lambda: the comprehension's final member.
STORED = "def f(xs, k):\n    return [lambda: x + k for x in xs]\n"


def _function(source: str, name: str = "f") -> FunctionDef:
    tree = SourceFile(
        (source, "lambda_cell.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    return next(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name == name
    )


def _lambdas(body) -> list:
    return [
        node
        for statement in body
        for node in statement.walk()
        if isinstance(node, Lambda)
    ]


def _outcome(tmp_path: Path, source: str, stem: str):
    path = tmp_path / f"{stem}.py"
    path.write_text(source, encoding="utf-8")
    functions = SourceFile(
        path_source(str(path)),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    ).functions()
    function = next(node for node in functions if node.name == "f")
    return function.sugar().desugar(None)


def _returned(outcome) -> list:
    """Every value a completed face of ``outcome`` returns; a lambda call's
    value is the body its producer reduced with the cells the call carried."""
    found: list = []

    def visit(value) -> None:
        if isinstance(value, (ReturnValue, GuardedReturn)):
            found.append(_resolved(value.value))
            return
        for entry in getattr(value, "statements", ()) or ():
            visit(entry)
        record = getattr(value, "record", None)
        if record is not None:
            visit(record)

    for exit_ in outcome_to_exitset(outcome).exits:
        if isinstance(exit_, Completed):
            visit(exit_.value)
    return found


def _resolved(value):
    retained = getattr(value, "retained_source_completion_outcome", None)
    outcome = retained() if callable(retained) else None
    if outcome is not None:
        inner = _returned(outcome)
        if inner:
            return inner[-1]
        return outcome_to_exitset(outcome).completed_value()
    if isinstance(value, CallSiteValue) and value.body is not None:
        dug = value._dig_floor_or_none(
            ReduceContext.root(owner="lambda-cell"), owner="lambda-cell"
        )
        if dug is not None:
            return dug
    return value


# ---------------------------------------------------------------------------
# The body reads a captured coordinate; the call carries the binding at it.
# ---------------------------------------------------------------------------


def test_the_lambda_reads_an_enclosing_local_through_a_captured_coordinate() -> None:
    (lam,) = _lambdas(_function(CALLED_AFTER_REBIND).substitute({}).body)
    names, coordinates = lam._captured_bindings()
    assert names == ("x",)
    assert isinstance(lam.body, BindingCoordinateRef)
    assert lam.body.coordinate.cid == coordinates[0].cid
    frame = lam.source_visible_call_frame()
    assert frame.captured_names == ("x",)
    assert tuple(item.cid for item in frame.captured_coordinates) == tuple(
        item.cid for item in coordinates
    )


def test_a_call_after_the_rebind_carries_the_rebound_binding() -> None:
    body = _function(CALLED_AFTER_REBIND).substitute({}).body
    rebind = [
        node
        for node in body
        if isinstance(node, Assign) and node.targets[0].id == "x"
    ][-1]
    ret = body[-1]
    assert isinstance(ret, Return)
    call = ret.value
    assert isinstance(call, Call)
    ((name, cell),) = call.closure_cells
    assert name == "x"
    assert isinstance(cell, EvaluationRef)
    assert cell.evaluation == projection_key(rebind.evaluation, "x")
    sugar = call.sugar()
    assert isinstance(sugar, ComputedCallSugar)
    ((carried, cid, _value),) = sugar.captured
    assert carried == "x"
    assert cid == sugar.source_call_frame.captured_coordinates[0].cid


def test_a_call_before_the_rebind_carries_the_first_binding() -> None:
    body = _function(CALLED_BEFORE_REBIND).substitute({}).body
    first = [
        node
        for node in body
        if isinstance(node, Assign) and node.targets[0].id == "x"
    ][0]
    call = next(
        node.value
        for node in body
        if isinstance(node, Assign) and node.targets[0].id == "r"
    )
    assert isinstance(call, Call)
    ((name, cell),) = call.closure_cells
    assert name == "x"
    assert cell.evaluation == projection_key(first.evaluation, "x")


def test_the_lambda_called_after_the_rebind_returns_2(tmp_path: Path) -> None:
    returned = _returned(_outcome(tmp_path, CALLED_AFTER_REBIND, "after"))
    assert TWO in returned, returned
    assert ONE not in returned, returned


def test_the_lambda_called_before_the_rebind_returns_1(tmp_path: Path) -> None:
    returned = _returned(_outcome(tmp_path, CALLED_BEFORE_REBIND, "before"))
    assert ONE in returned, returned
    assert TWO not in returned, returned


# ---------------------------------------------------------------------------
# Passed on: the binding at the call is not known, so the call is refused.
# ---------------------------------------------------------------------------


def test_a_lambda_passed_on_refuses_by_name() -> None:
    (lam,) = _lambdas(_function(PASSED_ON).substitute({}).body)
    assert lam._captured_bindings()[0] == ("x",)
    callable_ = lam.sugar().desugar(None).completed_value()
    assert isinstance(callable_, LambdaCallable)
    from sugar_lift_py_tests.callable_application import CallableApplication

    with pytest.raises(SugarNotWritten):
        callable_.callable_application_with(
            CallableApplication((ONE,), (), "passed-on-call"), None
        )


def test_a_lambda_at_module_level_captures_nothing() -> None:
    source = "x = 1\ng = lambda: x\n"
    tree = SourceFile(
        (source, "lambda_cell_module.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    lam = next(node for node in tree.nodes() if isinstance(node, Lambda))
    assert lam.substitute({})._captured_bindings() == ((), ())


# ---------------------------------------------------------------------------
# A stored comprehension lambda still reads the final member.
# ---------------------------------------------------------------------------


def test_a_stored_lambda_still_reads_the_final_member() -> None:
    (ret,) = _function(STORED).substitute({}).body
    comp = ret.value
    assert isinstance(comp, ListComp)
    coordinate = ListComp._generator_binding_coordinate(comp, 0, comp.generators[0])
    lam = comp.elt
    assert isinstance(lam, Lambda)
    # ``x`` is the comprehension's: read through its cell, never captured.
    reads = [node for node in lam.body.walk() if isinstance(node, EvaluationRef)]
    final = final_member_coordinate(coordinate)
    assert [read.evaluation for read in reads] == [final]
    assert all(read.cell is True for read in reads)
    # ``k`` is the function's: captured, bound by whoever calls the lambda.
    assert lam._captured_bindings()[0] == ("k",)


def test_a_lambda_called_in_place_reads_the_current_member() -> None:
    source = "def f(xs):\n    return [(lambda: x)() for x in xs]\n"
    (ret,) = _function(source).substitute({}).body
    comp = ret.value
    coordinate = ListComp._generator_binding_coordinate(comp, 0, comp.generators[0])
    lam = comp.elt.func
    assert lam._captured_bindings() == ((), ())
    assert isinstance(lam.body, EvaluationRef)
    assert lam.body.evaluation == coordinate
