from __future__ import annotations

import ast

import pytest
from factory_reduce import fol

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext
from sugar_lift_py_tests.factory import FactoryAuditRow, factory_panic, FactoryGapInfo
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic as FactoryGap
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.floor import CallSiteValue, TermValue
from sugar_lift_py_tests.ir import ctor, num, str_const
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.sugar.floor_terms import floor_to_term


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
        owner="object getattr",
    )


def _object_identity(class_name: str, blame: str):
    return ctor("py.object.identity", [str_const(class_name), str_const(blame)])


def test_missing_attribute_projects_to_getattr_dunder_bridge() -> None:
    source = """\
class Box:
    def __getattr__(self, name):
        return 1
"""

    value = _reduce_expr(source, "Box().missing")

    assert isinstance(value, CallSiteValue)
    assert value.target_name == "Box.__getattr__"
    assert fol(floor_to_term(value, owner="object getattr bridge")) == fol(
        ctor(
            "call:Box.__getattr__",
            [
                _object_identity("Box", "t.py:1:0"),
                str_const("missing"),
            ],
        )
    )


def test_constructor_field_wins_before_getattr_fallback() -> None:
    source = """\
class Box:
    def __init__(self):
        self.existing = 2

    def __getattr__(self, name):
        return 1
"""

    value = _reduce_expr(source, "Box().existing")

    assert value == TermValue(2)


def test_method_attribute_refuses_instead_of_getattr_fallback() -> None:
    source = """\
class Box:
    def known(self):
        return 2

    def __getattr__(self, name):
        return 1
"""

    with pytest.raises(FactoryGap) as raised:
        _reduce_expr(source, "Box().known")

    assert raised.value.info.to_json()["requested"] == "bound method attribute floor"
    assert "Box.known" in raised.value.info.to_json()["observed"]


def test_getattr_dunder_can_drive_array_index_value_demand() -> None:
    source = """\
class Box:
    def __getattr__(self, name):
        return 1
"""

    value = _reduce_expr(source, "[10, 20, 30][Box().missing]")

    assert value == TermValue(20)


def test_missing_attribute_without_getattr_refuses_when_gap_info_is_dataclass(
    monkeypatch,
) -> None:
    source = """\
class Box:
    pass
"""

    def keep_dataclass_info(
        self, info: FactoryGapInfo, audit_row: FactoryAuditRow
    ) -> None:
        self.info = info
        self.audit_row = audit_row
        RuntimeError.__init__(self, info.message)

    monkeypatch.setattr(factory_panic, "__init__", keep_dataclass_info)

    with pytest.raises(FactoryGap) as raised:
        _reduce_expr(source, "Box().missing")

    assert raised.value.info.requested == "constructor-bound field"
    assert raised.value.info.observed == "Box.missing"
