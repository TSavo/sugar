"""AnnAssignSugar: ``x: int = 5`` binds like Assign; annotation is carried.

Dominant unowned assign-family shape (measured): AnnAssign Name valued+bare
(~1183 of ~1345 unowned assign nodes in sugar-lift-py-tests). AssignSugar
owns only ``Assign`` with a single Name target -- AnnAssign is a different
node kind.
"""

from __future__ import annotations

import ast

from factory_reduce import compose_block

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import (
    BlockValue,
    BoundVar,
    ReturnValue,
    SupportValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.ir import ctor, make_var, str_const
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.sugar.ann_assign_sugar import AnnAssignSugar
from sugar_lift_py_tests.sugar.assign_sugar import AssignSugar


def _site(src: str):
    node = ast.parse(src).body[0]
    return SourceFragment.from_node(node, "t.py")


def _build_ann(src: str) -> AnnAssignSugar:
    node = ast.parse(src).body[0]
    if isinstance(node, ast.FunctionDef):
        node = next(s for s in node.body if isinstance(s, ast.AnnAssign))
    ctx = FactoryBuildContext(filename="f.py", catalog=default_catalog())
    result = build_node(node, filename="f.py", role=SugarRole.STATEMENT, ctx=ctx)
    assert isinstance(result.sugar, AnnAssignSugar)
    return result.sugar


# ---------------------------------------------------------------------------
# (1) positive: target binds to the value; annotation carried
# ---------------------------------------------------------------------------


def test_ann_assign_selects_ann_assign_sugar() -> None:
    sugar = _build_ann("x: int = 5")
    assert sugar.name == "x"
    assert sugar.value is not None
    assert sugar.annotation_kind in {"Name", "Constant", "Attribute", "Subscript"}


def test_valued_ann_assign_is_bound_var() -> None:
    sugar = _build_ann("x: int = 5")
    ctx = FactoryBuildContext(filename="f.py", catalog=default_catalog())
    bound = complete_value(sugar.desugar(ctx), owner="ann")
    assert isinstance(bound, BoundVar)
    assert bound.name == "x"


def test_ann_assign_then_return_recomposes_like_assign() -> None:
    """(1) ``x: int = 5; return x`` binds x to 5 -- same face as AssignSugar."""
    assert compose_block("    y: int = 5\n    return y\n") == BlockValue(
        (ReturnValue(TermValue(5)),)
    )


def test_annotation_carried_not_dropped() -> None:
    """Annotation reduces to python:type coordinate (BuiltinTypeNameSugar)."""
    sugar = _build_ann("x: int = 5")
    ctx = FactoryBuildContext(filename="f.py", catalog=default_catalog())
    ann_value = complete_value(sugar.annotation.reduce(ctx), owner="ann-type")
    assert isinstance(ann_value, SymbolicValue)
    assert ann_value.term == ctor("python:type", [str_const("int")])


# ---------------------------------------------------------------------------
# (2) discrimination: different values bind differently
# ---------------------------------------------------------------------------


def test_value_discriminates_the_binding() -> None:
    """``x: int = 5`` vs ``x: int = 6`` recompose different values."""
    five = compose_block("    x: int = 5\n    return x\n")
    six = compose_block("    x: int = 6\n    return x\n")
    assert five == BlockValue((ReturnValue(TermValue(5)),))
    assert six == BlockValue((ReturnValue(TermValue(6)),))
    assert five != six


def test_annotation_kind_discriminates_metadata() -> None:
    """Different annotations stay present on the sugar (not dropped)."""
    as_int = _build_ann("x: int = 5")
    as_str = _build_ann("x: str = 'a'")
    assert as_int.annotation_kind == "Name"
    assert as_str.annotation_kind == "Name"
    ctx = FactoryBuildContext(filename="f.py", catalog=default_catalog())
    int_term = complete_value(as_int.annotation.reduce(ctx), owner="a").term
    str_term = complete_value(as_str.annotation.reduce(ctx), owner="a").term
    assert int_term == ctor("python:type", [str_const("int")])
    assert str_term == ctor("python:type", [str_const("str")])
    assert int_term != str_term


def test_ann_assign_aliases_symbolic_carrier() -> None:
    assert compose_block(
        "    x: int = z\n    return x\n",
        binds={"z": SymbolicValue(make_var("z"))},
    ) == BlockValue((ReturnValue(SymbolicValue(make_var("z"))),))


# ---------------------------------------------------------------------------
# (3) structural: owns AnnAssign Name; not plain Assign; bare is support
# ---------------------------------------------------------------------------


def test_owns_ann_assign_not_plain_assign() -> None:
    assert AnnAssignSugar.owns(_site("x: int = 5")) is True
    assert AnnAssignSugar.owns(_site("x: int")) is True
    assert AnnAssignSugar.owns(_site("x = 5")) is False
    assert AssignSugar.owns(_site("x = 5")) is True
    assert AssignSugar.owns(_site("x: int = 5")) is False

    catalog = default_catalog()
    ann = [
        c.name for c in catalog.candidates_for(SugarRole.STATEMENT, _site("x: int = 5"))
    ]
    plain = [
        c.name for c in catalog.candidates_for(SugarRole.STATEMENT, _site("x = 5"))
    ]
    assert "AnnAssignSugar" in ann
    assert "AssignSugar" not in ann
    assert "AssignSugar" in plain
    assert "AnnAssignSugar" not in plain


def test_annotation_only_ann_assign_is_support() -> None:
    """Bare ``x: int`` is a declaration -- support, no binding."""
    sugar = _build_ann("x: int")
    ctx = FactoryBuildContext(filename="f.py", catalog=default_catalog())
    value = complete_value(sugar.desugar(ctx), owner="ann")
    assert isinstance(value, SupportValue)
    assert sugar.value is None
    # Annotation still carried on the sugar.
    assert sugar.annotation_kind == "Name"


def test_attr_ann_assign_has_its_distinct_attribute_owner() -> None:
    src = "class C:\n    def m(self):\n        self.x: int = 1\n"
    mod = ast.parse(src)
    ann = next(n for n in ast.walk(mod) if isinstance(n, ast.AnnAssign))
    ctx = FactoryBuildContext(filename="f.py", catalog=default_catalog())
    built = build_node(ann, filename="f.py", role=SugarRole.STATEMENT, ctx=ctx)

    assert type(built.sugar).__name__ == "AttributeAnnAssignSugar"
