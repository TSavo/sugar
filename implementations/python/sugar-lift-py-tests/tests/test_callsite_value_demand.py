from __future__ import annotations

import ast

import pytest

from factory_reduce import fol

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext, ReduceContext
from sugar_lift_py_tests.factory import factory_panic, SourceFragment
from sugar_lift_py_tests.factory.block import Block
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.floor import (
    ArrayLiteral,
    BlockValue,
    BoolValue,
    CallSiteValue,
    GuardedReturn,
    ObjectValue,
    ReturnValue,
    TermValue,
)
from sugar_lift_py_tests.floor.call_site_value import force_floor
from sugar_lift_py_tests.ir import ctor, num, str_const
from sugar_lift_py_tests.operations import BinaryOperatorOperation, perform_operation
from sugar_lift_py_tests.outcome import Complete, complete_value
from sugar_lift_py_tests.sugar.floor_terms import floor_to_term
from sugar_lift_py_tests.sugar.object_equality_term_sugar import ObjectEqualityTermSugar
from sugar_lift_py_tests.sugar_body import SugarBody


def _ctx_for_module(source: str) -> FactoryBuildContext:
    module = ast.parse(source)
    resolver = {
        stmt.name: stmt
        for stmt in module.body
        if isinstance(stmt, (ast.FunctionDef, ast.ClassDef))
    }
    return FactoryBuildContext(
        filename="t.py",
        catalog=default_catalog(),
        name_resolver=resolver,
    )


def _reduce_expr(source: str, expr: str):
    ctx = _ctx_for_module(source)
    node = ast.parse(expr, mode="eval").body
    return complete_value(
        ctx.build_body(node, SugarRole.TERM).reduce(ctx),
        owner="callsite value demand",
    )


def _reduce_function_return(source: str, name: str):
    module = ast.parse(source)
    ctx = _ctx_for_module(source)
    function = next(
        stmt
        for stmt in module.body
        if isinstance(stmt, ast.FunctionDef) and stmt.name == name
    )
    block = ctx.build_body(Block.of(function.body), SugarRole.STATEMENT)
    value = complete_value(block.reduce(ctx), owner="function return demand")
    assert len(value.statements) == 1
    returned = value.statements[0]
    assert isinstance(returned, ReturnValue)
    return returned.value


def _callsite_value(
    source: str, expr: str
) -> tuple[CallSiteValue, FactoryBuildContext]:
    ctx = _ctx_for_module(source)
    node = ast.parse(expr, mode="eval").body
    value = complete_value(
        ctx.build_body(node, SugarRole.TERM).reduce(ctx),
        owner="callsite value demand",
    )
    assert isinstance(value, CallSiteValue)
    return value, ctx


def test_control_flow_body_callsite_can_force_floor_through_block_sugar() -> None:
    source = """\
def f(x):
    if x == 1:
        return 1
    return 0
"""

    callsite, ctx = _callsite_value(source, "f(1)")
    demand_ctx = ReduceContext.root(owner="control-flow callsite demand")

    floor = force_floor(callsite, demand_ctx, owner="control-flow callsite demand")

    assert isinstance(floor, BlockValue)
    assert len(floor.statements) == 2
    assert all(isinstance(statement, GuardedReturn) for statement in floor.statements)
    assert demand_ctx.operation_log[-1] == (
        "control-flow callsite demand",
        "project_callsite_with",
        "CallsiteProjectionOperation",
    )


def test_terminating_callsite_chain_forces_exact_literal_floor() -> None:
    source = """\
def b():
    return 0

def a():
    return b()
"""

    callsite, ctx = _callsite_value(source, "a()")

    assert force_floor(callsite, ctx, owner="terminating chain demand") == TermValue(0)


def test_mutual_recursion_refuses_floor_honestly_without_false_literal() -> None:
    values: dict[str, CallSiteValue] = {}

    class ReturnCallsiteSugar:
        def __init__(self, target: str) -> None:
            self.target = target

        def desugar(self, ctx=None):
            del ctx
            return Complete(values[self.target])

    values["a"] = CallSiteValue(
        target_name="a",
        arg_values=(),
        parameters=(),
        term=ctor("call:a", []),
        body=SugarBody(ReturnCallsiteSugar("b"), SugarRole.TERM),
    )
    values["b"] = CallSiteValue(
        target_name="b",
        arg_values=(),
        parameters=(),
        term=ctor("call:b", []),
        body=SugarBody(ReturnCallsiteSugar("a"), SugarRole.TERM),
    )
    ctx = ReduceContext.root(owner="mutual recursion demand")

    with pytest.raises(FactoryGap) as raised:
        force_floor(values["a"], ctx, owner="mutual recursion demand")

    assert raised.value.info.to_json()["gap_kind"] == "Floor"
    assert raised.value.info.to_json()["observed"] == "recursive callsite value demand"
    assert raised.value.info.to_json()["requested"] == "force callsite floor"


def test_callsite_force_floor_budget_refuses_deep_unique_chain() -> None:
    values: dict[str, CallSiteValue | TermValue] = {"leaf": TermValue(0)}

    class ReturnFloorSugar:
        def __init__(self, target: str) -> None:
            self.target = target

        def desugar(self, ctx=None):
            del ctx
            return Complete(values[self.target])

    values["c2"] = CallSiteValue(
        target_name="c2",
        arg_values=(),
        parameters=(),
        term=ctor("call:c2", []),
        body=SugarBody(ReturnFloorSugar("leaf"), SugarRole.TERM),
    )
    values["c1"] = CallSiteValue(
        target_name="c1",
        arg_values=(),
        parameters=(),
        term=ctor("call:c1", []),
        body=SugarBody(ReturnFloorSugar("c2"), SugarRole.TERM),
    )
    values["c0"] = CallSiteValue(
        target_name="c0",
        arg_values=(),
        parameters=(),
        term=ctor("call:c0", []),
        body=SugarBody(ReturnFloorSugar("c1"), SugarRole.TERM),
    )
    ctx = ReduceContext.root(owner="deep chain demand")

    with pytest.raises(FactoryGap) as raised:
        force_floor(values["c0"], ctx, owner="deep chain demand", budget=2)

    assert raised.value.info.to_json()["gap_kind"] == "Floor"
    assert (
        raised.value.info.to_json()["observed"]
        == "callsite value demand budget exhausted"
    )
    assert raised.value.info.to_json()["requested"] == "force callsite floor"


def test_effectful_callsite_refuses_floor_without_fabricated_value() -> None:
    source = """\
def f():
    return 1 // 0
"""

    callsite, ctx = _callsite_value(source, "f()")

    with pytest.raises(FactoryGap) as raised:
        force_floor(callsite, ctx, owner="effectful callsite demand")

    assert raised.value.info.to_json()["gap_kind"] == "Floor"
    assert raised.value.info.to_json()["observed"] == "Incomplete"
    assert "runtime effect" in raised.value.info.to_json()["fix"]


def test_callsite_projects_to_bridge_but_floors_only_when_value_is_demanded() -> None:
    source = """\
def h():
    return 1

def g():
    return h()

def f():
    return g()
"""

    call_value = _reduce_expr(source, "f()")
    assert fol(floor_to_term(call_value, owner="callsite projection")) == fol(
        ctor("call:f", [])
    )

    indexed = _reduce_expr(source, "[10, 20, 30][f()]")
    assert indexed == TermValue(20)


def test_object_constructor_can_stand_inside_array_literal_as_identity_floor() -> None:
    source = """\
class Mult:
    pass
"""

    value = _reduce_expr(source, "[Mult()]")

    assert isinstance(value, ArrayLiteral)
    assert isinstance(value.items[0], ObjectValue)
    assert fol(floor_to_term(value, owner="object array")) == fol(
        ctor(
            "array",
            [
                ctor(
                    "py.object.identity",
                    [str_const("Mult"), str_const("t.py:1:1")],
                )
            ],
        )
    )


def test_constructor_bound_field_can_drive_array_index_value_demand() -> None:
    source = """\
class X:
    def __init__(self, y):
        self.x = y

def t():
    x = X(1)
    return [10, 20, 30][x.x]
"""

    assert _reduce_function_return(source, "t") == TermValue(20)


def test_constructor_method_return_can_drive_array_index_value_demand() -> None:
    source = """\
class X:
    def __init__(self, y):
        self.x = y

    def getX(self):
        return self.x

def t():
    x = X(1)
    return [10, 20, 30][x.getX()]
"""

    assert _reduce_function_return(source, "t") == TermValue(20)


def test_object_multiply_projects_to_dunder_method_bridge() -> None:
    source = """\
class Mult:
    def __mul__(self, other):
        return 1
"""

    value = _reduce_expr(source, "Mult() * Mult()")

    assert isinstance(value, CallSiteValue)
    assert fol(floor_to_term(value, owner="object multiply")) == fol(
        ctor(
            "call:Mult.__mul__",
            [
                ctor(
                    "py.object.identity",
                    [str_const("Mult"), str_const("t.py:1:0")],
                ),
                ctor(
                    "py.object.identity",
                    [str_const("Mult"), str_const("t.py:1:9")],
                ),
            ],
        )
    )


def test_object_multiply_can_drive_array_index_value_demand() -> None:
    source = """\
class X:
    def __init__(self, y):
        self.x = y

    def __mul__(self, other):
        return other.x
"""

    value = _reduce_expr(source, "[10, 20, 30][X(0) * X(1)]")

    assert value == TermValue(20)


def test_object_equality_projects_to_dunder_method_bridge() -> None:
    source = """\
class Eq:
    def __eq__(self, other):
        return 1
"""

    fragment = SourceFragment.from_node(
        ast.parse("Eq() == Eq()", mode="eval").body, "t.py"
    )
    assert ObjectEqualityTermSugar.owns(fragment)

    value = _reduce_expr(source, "Eq() == Eq()")

    assert isinstance(value, CallSiteValue)
    assert fol(floor_to_term(value, owner="object equality")) == fol(
        ctor(
            "call:Eq.__eq__",
            [
                ctor(
                    "py.object.identity",
                    [str_const("Eq"), str_const("t.py:1:0")],
                ),
                ctor(
                    "py.object.identity",
                    [str_const("Eq"), str_const("t.py:1:8")],
                ),
            ],
        )
    )


def test_methodless_object_equality_uses_identity_not_structure() -> None:
    source = """\
class C:
    def __init__(self, x):
        self.x = x
"""

    value = _reduce_expr(source, "C(5) == C(5)")

    assert value == BoolValue(False)


def test_methodless_object_equality_refuses_without_identity_testimony() -> None:
    receiver = ObjectValue(class_name="C", fields=())
    right = ObjectValue(class_name="C", fields=())

    with pytest.raises(FactoryGap) as raised:
        perform_operation(
            owner="object equality identity",
            blame="t.py:1:0",
            receiver=receiver,
            operation=BinaryOperatorOperation(
                operator="==",
                right=right,
                owner="object equality identity",
                blame="t.py:1:0",
            ),
            ctx=ReduceContext.root(owner="object equality identity"),
        )

    assert raised.value.info.to_json()["requested"] == "object identity equality"
    assert "ObjectValue identities" in raised.value.info.to_json()["fix"]


def test_reflected_object_multiply_projects_to_dunder_method_bridge() -> None:
    source = """\
class Mult:
    def __rmul__(self, other):
        return 1
"""

    value = _reduce_expr(source, "2 * Mult()")

    assert isinstance(value, CallSiteValue)
    assert fol(floor_to_term(value, owner="reflected object multiply")) == fol(
        ctor(
            "call:Mult.__rmul__",
            [
                ctor(
                    "py.object.identity",
                    [str_const("Mult"), str_const("t.py:1:4")],
                ),
                num(2),
            ],
        )
    )


def test_reflected_object_multiply_can_drive_array_index_value_demand() -> None:
    source = """\
class X:
    def __init__(self, y):
        self.x = y

    def __rmul__(self, other):
        return self.x
"""

    value = _reduce_expr(source, "[10, 20, 30][2 * X(1)]")

    assert value == TermValue(20)


def test_object_add_projects_to_dunder_method_bridge() -> None:
    source = """\
class Add:
    def __add__(self, other):
        return 1
"""

    value = _reduce_expr(source, "Add() + Add()")

    assert isinstance(value, CallSiteValue)
    assert fol(floor_to_term(value, owner="object add")) == fol(
        ctor(
            "call:Add.__add__",
            [
                ctor(
                    "py.object.identity",
                    [str_const("Add"), str_const("t.py:1:0")],
                ),
                ctor(
                    "py.object.identity",
                    [str_const("Add"), str_const("t.py:1:8")],
                ),
            ],
        )
    )


def test_reflected_object_add_can_drive_array_index_value_demand() -> None:
    source = """\
class X:
    def __init__(self, y):
        self.x = y

    def __radd__(self, other):
        return self.x
"""

    value = _reduce_expr(source, "[10, 20, 30][2 + X(1)]")

    assert value == TermValue(20)


def test_object_inplace_add_can_drive_array_index_value_demand() -> None:
    source = """\
class X:
    def __init__(self, y):
        self.x = y

    def __iadd__(self, other):
        return other.x

def t():
    x = X(0)
    x += X(1)
    return [10, 20, 30][x]
"""

    try:
        value = _reduce_function_return(source, "t")
    except FactoryGap as exc:
        pytest.fail(f"object inplace add should dispatch to __iadd__: {exc}")

    assert value == TermValue(20)


def test_object_inplace_add_value_demand_distinguishes_self_from_rhs() -> None:
    source = """\
class X:
    def __init__(self, y):
        self.x = y

    def __iadd__(self, other):
        return self.x

def t():
    x = X(0)
    x += X(1)
    return [10, 20, 30][x]
"""

    value = _reduce_function_return(source, "t")

    assert value == TermValue(10)


@pytest.mark.parametrize(
    ("method_name", "statement"),
    [
        ("__iadd__", "x += Op()"),
        ("__isub__", "x -= Op()"),
        ("__imul__", "x *= Op()"),
        ("__imatmul__", "x @= Op()"),
        ("__itruediv__", "x /= Op()"),
        ("__ifloordiv__", "x //= Op()"),
        ("__imod__", "x %= Op()"),
        ("__ipow__", "x **= Op()"),
        ("__ilshift__", "x <<= Op()"),
        ("__irshift__", "x >>= Op()"),
        ("__iand__", "x &= Op()"),
        ("__ixor__", "x ^= Op()"),
        ("__ior__", "x |= Op()"),
    ],
)
def test_expanded_object_inplace_binary_projects_to_dunder_method_bridge(
    method_name: str, statement: str
) -> None:
    source = f"""\
class Op:
    def {method_name}(self, other):
        return 1

def t():
    x = Op()
    {statement}
    return x
"""

    value = _reduce_function_return(source, "t")

    assert isinstance(value, CallSiteValue)
    assert value.target_name == f"Op.{method_name}"
    assert len(value.arg_values) == 2


def test_object_subtract_projects_to_dunder_method_bridge() -> None:
    source = """\
class Sub:
    def __sub__(self, other):
        return 1
"""

    value = _reduce_expr(source, "Sub() - Sub()")

    assert isinstance(value, CallSiteValue)
    assert fol(floor_to_term(value, owner="object subtract")) == fol(
        ctor(
            "call:Sub.__sub__",
            [
                ctor(
                    "py.object.identity",
                    [str_const("Sub"), str_const("t.py:1:0")],
                ),
                ctor(
                    "py.object.identity",
                    [str_const("Sub"), str_const("t.py:1:8")],
                ),
            ],
        )
    )


def test_reflected_object_subtract_can_drive_array_index_value_demand() -> None:
    source = """\
class X:
    def __init__(self, y):
        self.x = y

    def __rsub__(self, other):
        return self.x
"""

    value = _reduce_expr(source, "[10, 20, 30][2 - X(1)]")

    assert value == TermValue(20)


@pytest.mark.parametrize(
    ("method_name", "expr"),
    [
        ("__truediv__", "Op() / Op()"),
        ("__floordiv__", "Op() // Op()"),
        ("__mod__", "Op() % Op()"),
        ("__pow__", "Op() ** Op()"),
        ("__matmul__", "Op() @ Op()"),
        ("__and__", "Op() & Op()"),
        ("__or__", "Op() | Op()"),
        ("__xor__", "Op() ^ Op()"),
        ("__lshift__", "Op() << Op()"),
        ("__rshift__", "Op() >> Op()"),
    ],
)
def test_expanded_object_binary_projects_to_dunder_method_bridge(
    method_name: str, expr: str
) -> None:
    source = f"""\
class Op:
    def {method_name}(self, other):
        return 1
"""

    value = _reduce_expr(source, expr)

    assert isinstance(value, CallSiteValue)
    assert value.target_name == f"Op.{method_name}"
    assert len(value.arg_values) == 2


@pytest.mark.parametrize(
    ("method_name", "expr"),
    [
        ("__rtruediv__", "2 / Op()"),
        ("__rfloordiv__", "2 // Op()"),
        ("__rmod__", "2 % Op()"),
        ("__rpow__", "2 ** Op()"),
        ("__rmatmul__", "2 @ Op()"),
        ("__rand__", "2 & Op()"),
        ("__ror__", "2 | Op()"),
        ("__rxor__", "2 ^ Op()"),
        ("__rlshift__", "2 << Op()"),
        ("__rrshift__", "2 >> Op()"),
    ],
)
def test_expanded_reflected_object_binary_projects_to_dunder_method_bridge(
    method_name: str, expr: str
) -> None:
    source = f"""\
class Op:
    def {method_name}(self, other):
        return 1
"""

    value = _reduce_expr(source, expr)

    assert isinstance(value, CallSiteValue)
    assert value.target_name == f"Op.{method_name}"
    assert len(value.arg_values) == 2


@pytest.mark.parametrize(
    ("method_name", "expr"),
    [
        ("__pos__", "+Op()"),
        ("__neg__", "-Op()"),
        ("__invert__", "~Op()"),
    ],
)
def test_object_unary_projects_to_dunder_method_bridge(
    method_name: str, expr: str
) -> None:
    source = f"""\
class Op:
    def {method_name}(self):
        return 1
"""

    value = _reduce_expr(source, expr)

    assert isinstance(value, CallSiteValue)
    assert value.target_name == f"Op.{method_name}"
    assert len(value.arg_values) == 1


def test_expanded_object_binary_can_drive_array_index_value_demand() -> None:
    source = """\
class X:
    def __init__(self, y):
        self.x = y

    def __truediv__(self, other):
        return other.x
"""

    value = _reduce_expr(source, "[10, 20, 30][X(0) / X(1)]")

    assert value == TermValue(20)


def test_object_unary_can_drive_array_index_value_demand() -> None:
    source = """\
class X:
    def __init__(self, y):
        self.x = y

    def __neg__(self):
        return self.x
"""

    value = _reduce_expr(source, "[10, 20, 30][-X(1)]")

    assert value == TermValue(20)
