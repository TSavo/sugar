from __future__ import annotations

import ast

import pytest

from factory_reduce import fol

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor import CallSiteValue, StringValue, SymbolicValue
from sugar_lift_py_tests.floor.call_site_value import force_floor
from sugar_lift_py_tests.ir import ctor, str_const
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.sugar.format_dunder_call_sugar import FormatDunderCallSugar
from sugar_lift_py_tests.sugar.floor_terms import floor_to_term
from sugar_lift_py_tests.sugar.witnesses import SugarWitnessPair
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


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
    value = complete_value(
        ctx.build_body(node, SugarRole.TERM).reduce(ctx),
        owner="display conversion dunder bridge",
    )
    return value, ctx


def _object_identity(class_name: str, blame: str):
    return ctor("py.object.identity", [str_const(class_name), str_const(blame)])


def test_str_builtin_projects_object_to_dunder_method_bridge() -> None:
    source = """\
class Box:
    def __str__(self):
        return "display"
"""

    value, ctx = _reduce_expr(source, "str(Box())")

    assert isinstance(value, CallSiteValue)
    assert value.target_name == "Box.__str__"
    assert fol(floor_to_term(value, owner="str dunder bridge")) == fol(
        ctor("call:Box.__str__", [_object_identity("Box", "t.py:1:4")])
    )
    assert force_floor(value, ctx, owner="str dunder bridge") == StringValue("display")


def test_bytes_builtin_projects_object_to_dunder_method_bridge() -> None:
    source = """\
class Box:
    def __bytes__(self):
        return b"OK"
"""

    value, ctx = _reduce_expr(source, "bytes(Box())")

    assert isinstance(value, CallSiteValue)
    assert value.target_name == "Box.__bytes__"
    assert fol(floor_to_term(value, owner="bytes dunder bridge")) == fol(
        ctor("call:Box.__bytes__", [_object_identity("Box", "t.py:1:6")])
    )
    assert force_floor(value, ctx, owner="bytes dunder bridge") == SymbolicValue(
        ctor("python:bytes", [str_const("4f4b")])
    )


def test_format_builtin_projects_object_to_dunder_method_bridge() -> None:
    source = """\
class Box:
    def __format__(self, spec):
        return spec
"""

    value, ctx = _reduce_expr(source, 'format(Box(), "brief")')

    assert isinstance(value, CallSiteValue)
    assert value.target_name == "Box.__format__"
    assert fol(floor_to_term(value, owner="format dunder bridge")) == fol(
        ctor(
            "call:Box.__format__",
            [_object_identity("Box", "t.py:1:7"), str_const("brief")],
        )
    )
    assert force_floor(value, ctx, owner="format dunder bridge") == StringValue("brief")


def test_format_builtin_without_spec_passes_empty_format_spec() -> None:
    source = """\
class Box:
    def __format__(self, spec):
        return spec
"""

    value, ctx = _reduce_expr(source, "format(Box())")

    assert isinstance(value, CallSiteValue)
    assert value.target_name == "Box.__format__"
    assert fol(floor_to_term(value, owner="format dunder bridge")) == fol(
        ctor(
            "call:Box.__format__",
            [_object_identity("Box", "t.py:1:7"), str_const("")],
        )
    )
    assert force_floor(value, ctx, owner="format dunder bridge") == StringValue("")


def test_format_builtin_constructs_opaque_callsite_dunder_coordinate() -> None:
    source = """\
def build_box():
    return external_box()
"""

    receiver, ctx = _reduce_expr(source, "external_box()")
    value, _ = _reduce_expr(source, 'format(external_box(), "brief")')

    assert isinstance(receiver, CallSiteValue)
    assert isinstance(value, CallSiteValue)
    assert value.target_name == "__format__"
    assert value.arg_values == (receiver, StringValue("brief"))
    assert fol(floor_to_term(value, owner="callsite format bridge")) == fol(
        ctor(
            "call:__format__",
            [
                receiver.to_term(owner="callsite format bridge"),
                str_const("brief"),
            ],
            symbol_kind="method-coordinate",
        )
    )


def test_format_callsite_body_construction_gap_stays_loud() -> None:
    source = """\
def build():
    return format([1], "inner")
"""

    with pytest.raises(FactoryPanic, match="owner=FormatDunderCallSugar"):
        _reduce_expr(source, 'format(build(), "outer")')


def test_callsite_format_coordinate_wrong_twin_refutes(tmp_path) -> None:
    witnesses = FormatDunderCallSugar.witnesses()
    pair = next(
        witness
        for witness in witnesses
        if isinstance(witness, SugarWitnessPair)
        and witness.name == "callsite_format_coordinate"
    )

    truthful = run_source_through_real_solver(
        tmp_path / "format-callsite-truthful", pair.truthful.source
    )
    lying = run_source_through_real_solver(
        tmp_path / "format-callsite-lying", pair.lying.source
    )

    assert truthful.verdict == pair.truthful.expected == "sat"
    assert lying.verdict == pair.lying.expected == "unsat"
    assert "FormatDunderCallSugar" in truthful.selected_sugars
    assert "FormatDunderCallSugar" in lying.selected_sugars


def test_production_lift_constructs_format_dunder_return_without_factory_panic() -> (
    None
):
    """#4400: bare ClassDef must enroll so format(Box()) is ObjectValue, not transport death.

    The witness seed rides the production audit door. Without bare class nodes in
    name_resolver, ConstructorCallSugar falls back to an opaque CallSiteValue and
    FormatDunderCallSugar dies in FloorValue.format_data_model. Enrollment makes the
    constructor ObjectValue with __format__, so the lift returns proof-bearing IR.
    """
    from sugar_lift_py_tests.lift_rpc import audit_lift_file

    source = (
        "class Box:\n"
        "    def __format__(self, spec):\n"
        "        return spec\n"
        "\n"
        "def A():\n"
        "    return format(Box(), 'x')\n"
        "\n"
        "def test_a():\n"
        "    assert A() == 'x'\n"
    )

    payload, gaps = audit_lift_file(source, "format_dunder_return.py")
    rpc = payload.to_rpc()
    selected = {
        row["selected"]
        for row in [
            *rpc.get("factoryAuditSummary", {}).get("factoryWalk", []),
            *rpc.get("factoryAudits", []),
        ]
        if isinstance(row, dict) and isinstance(row.get("selected"), str)
    }

    assert gaps == []
    assert "FormatDunderCallSugar" in selected
    assert "ConstructorCallSugar" in selected
    assert rpc.get("ir"), "format dunder return must emit proof-bearing IR"
    recovered = audit_lift_file(source, "format_dunder_return.py", recover_panics=True)
    assert recovered.panics == []
