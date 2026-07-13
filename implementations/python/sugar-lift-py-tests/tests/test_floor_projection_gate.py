from __future__ import annotations

import ast
from pathlib import Path

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor import FloorValue, FunctionCallable, TermValue
from sugar_lift_py_tests.ir import bool_const, make_var, num
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
from sugar_lift_py_tests.sugar.floor_terms import floor_to_term


def test_term_value_projects_via_ownership() -> None:
    assert TermValue(3).to_term(owner="test") == num(3)
    assert floor_to_term(TermValue(3), owner="test") == num(3)


def test_term_value_nonfinite_float_does_not_hard_crash_to_term() -> None:
    """#4155 wall: int(inf) must not kill the lift RPC mid-package.

    Integral floats still take the Int arm; inf/nan take the Real arm.
    """
    from sugar_lift_py_tests.ir import real_lit

    assert TermValue(3.0).to_term(owner="test") == num(3)
    inf_term = TermValue(float("inf")).to_term(owner="test")
    nan_term = TermValue(float("nan")).to_term(owner="test")
    assert inf_term == real_lit("Infinity")
    # nan str is platform-stable 'nan' via Decimal(str(nan))
    assert nan_term == real_lit("NaN") or str(nan_term).lower().find("nan") >= 0


def test_production_bool_floor_projects_via_ownership() -> None:
    node = ast.parse("True", mode="eval").body
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())

    sugar = build_node(node, filename="t.py", role=SugarRole.TERM, ctx=ctx).sugar

    assert isinstance(sugar, TrueBoolLiteralSugar)
    assert sugar.to_term(owner="test") == bool_const(True)


def test_unprojectable_floor_value_gap_panics() -> None:
    class NewFloor(FloorValue):
        pass

    with pytest.raises(FactoryPanic) as exc:
        NewFloor().to_term(owner="test")
    assert exc.value.info.to_json()["gap_kind"] == "Floor"
    assert exc.value.info.to_json()["gap_locus"] == "Projection"


def test_named_function_callable_projects_as_its_binding_coordinate() -> None:
    assert FunctionCallable(name="helper").to_term(owner="post") == make_var("helper")


_FLOOR_TYPES = {
    "ArrayLiteral",
    "BlockValue",
    "FalseBoolLiteralSugar",
    "BoundVar",
    "BuilderState",
    "Bv32Value",
    "CallSiteValue",
    "EncodedStringValue",
    "FloorValue",
    "FunctionCallable",
    "GuardedRaise",
    "GuardedReturn",
    "ImportAliasValue",
    "LambdaCallable",
    "ObjectMethodValue",
    "ObjectValue",
    "PredicateValue",
    "RaiseValue",
    "ReturnValue",
    "SequenceConstructor",
    "SliceValue",
    "StringValue",
    "SupportValue",
    "SymbolicValue",
    "TermValue",
    "TrueBoolLiteralSugar",
    "TupleLiteralValue",
}
_ALLOWED_DIRS = ("floor/", "operations/")
_LADDER_THRESHOLD = 3
_RATCHETED_NON_PROJECTION_LADDERS = {
    # Control-flow body construction classifies return floor outcomes and the
    # encoder special case. Keep as a named ratchet until that ownership moves.
    "factory/sugar_constructors.py:build_control_flow_body_sugar": 4,
    # Block sequencing owns statement effects/binds/returns/raises; it is the
    # sequencing borderline called out in the Task 7 plan.
    "sugar/block_sugar.py:fold_with_context": 6,
}


def test_no_floorvalue_isinstance_ladders_outside_the_floor() -> None:
    src = Path(__file__).resolve().parent.parent / "src" / "sugar_lift_py_tests"
    offenders = []
    for path in sorted(src.rglob("*.py")):
        rel = str(path.relative_to(src))
        if rel.startswith(_ALLOWED_DIRS) or "__pycache__" in rel:
            continue
        tree = ast.parse(path.read_text(), filename=rel)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            hits = 0
            for sub in ast.walk(node):
                if not (
                    isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Name)
                    and sub.func.id == "isinstance"
                    and len(sub.args) == 2
                ):
                    continue
                type_names = {
                    name.id
                    for name in ast.walk(sub.args[1])
                    if isinstance(name, ast.Name)
                }
                if type_names & _FLOOR_TYPES:
                    hits += 1
            if hits >= _LADDER_THRESHOLD:
                ratchet_key = f"{rel}:{node.name}"
                ratchet_max = _RATCHETED_NON_PROJECTION_LADDERS.get(ratchet_key)
                if ratchet_max is not None and hits <= ratchet_max:
                    continue
                offenders.append(f"{rel}:{node.lineno} {node.name} ({hits} checks)")
    assert not offenders, (
        "FloorValue projection ladders outside floor/+operations/ -- "
        "the value owns its projection; write to_term/a floor method instead:\n"
        + "\n".join(offenders)
    )
