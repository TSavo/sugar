"""ClassDefSugar: class body threads; bases ride as coordinates.

Plain `class C:` / `class C(Base):` only. Decorators and metaclass keywords
stay loud gaps.
"""

from __future__ import annotations

import ast

import pytest

from factory_reduce import compose_block

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import (
    BlockValue,
    ClassValue,
    SymbolicValue,
    UniverseValue,
)
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.sugar.class_def_sugar import ClassDefSugar


def _site(source: str):
    node = ast.parse(source).body[0]
    return SourceFragment.from_node(node, "t.py")


def _class_value(source: str, *, binds: dict | None = None) -> ClassValue:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    if binds:
        from dataclasses import replace
        from sugar_lift_py_tests.temporal import TemporalContext

        temporal = TemporalContext.empty()
        for name, value in binds.items():
            temporal = temporal.bind_value(name, value)
        ctx = replace(ctx, temporal=temporal)
    node = ast.parse(source).body[0]
    result = build_node(node, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)
    value = complete_value(result.sugar.desugar(ctx), owner="test")
    assert isinstance(value, ClassValue)
    return value


def test_class_body_method_threads_into_the_record() -> None:
    """(1) Method FunctionDef in the body becomes a UniverseValue contribution."""
    cls = _class_value(
        "class C:\n"
        "    def m(self):\n"
        "        return 1\n"
    )
    assert cls.name == "C"
    assert cls.bases == ()
    # Body contribution is the method universe.
    entries = cls.contribution()
    assert len(entries) == 1
    assert isinstance(entries[0], UniverseValue)
    assert entries[0].name == "m"
    assert entries[0].formals == ("self",)


def test_class_bases_are_carried_as_coordinates() -> None:
    """(1) Bases reduce to type coordinates (not dropped)."""
    cls = _class_value(
        "class C(Base):\n"
        "    pass\n",
        binds={"Base": SymbolicValue(make_var("Base"))},
    )
    assert cls.name == "C"
    assert len(cls.bases) == 1
    assert cls.bases[0] == SymbolicValue(make_var("Base"))
    assert cls.base_terms() == (make_var("Base"),)


def test_base_or_body_discriminates() -> None:
    """(2) Different base or body method produces a different contribution."""
    with_base_a = _class_value(
        "class C(A):\n"
        "    pass\n",
        binds={"A": SymbolicValue(make_var("A"))},
    )
    with_base_b = _class_value(
        "class C(B):\n"
        "    pass\n",
        binds={"B": SymbolicValue(make_var("B"))},
    )
    assert with_base_a.bases[0] != with_base_b.bases[0]
    assert with_base_a.base_terms() != with_base_b.base_terms()

    with_m = _class_value(
        "class C:\n"
        "    def m(self):\n"
        "        return 1\n"
    )
    with_n = _class_value(
        "class C:\n"
        "    def n(self):\n"
        "        return 1\n"
    )
    assert with_m.contribution()[0].name == "m"
    assert with_n.contribution()[0].name == "n"
    assert with_m.contribution()[0].name != with_n.contribution()[0].name


def test_class_binds_name_for_later_reference() -> None:
    """Class statement extends scope so a later name resolves to ClassValue."""
    block = compose_block(
        "    class C:\n"
        "        pass\n"
        "    return C\n",
    )
    assert isinstance(block, BlockValue)
    # Class body is empty (pass is support); return resolves C.
    from sugar_lift_py_tests.floor import ReturnValue

    ret = [s for s in block.statements if isinstance(s, ReturnValue)]
    assert len(ret) == 1
    assert isinstance(ret[0].value, ClassValue)
    assert ret[0].value.name == "C"


def test_owns_plain_class_not_decorated_metaclass_or_function() -> None:
    """(3) owns plain class; not decorated, metaclass, or FunctionDef."""
    assert ClassDefSugar.owns(_site("class C:\n    pass\n")) is True
    assert ClassDefSugar.owns(_site("class C(Base):\n    pass\n")) is True
    assert ClassDefSugar.owns(_site("class C(A, B):\n    pass\n")) is True
    assert ClassDefSugar.owns(_site("@dec\nclass C:\n    pass\n")) is False
    assert ClassDefSugar.owns(_site("class C(metaclass=M):\n    pass\n")) is False
    assert ClassDefSugar.owns(_site("def f():\n    pass\n")) is False

    catalog = default_catalog()
    plain = _site("class C:\n    pass\n")
    assert any(
        c.name == "ClassDefSugar"
        for c in catalog.candidates_for(SugarRole.STATEMENT, plain)
    )


def test_decorated_class_is_a_loud_factory_gap() -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse("@dec\nclass C:\n    pass\n").body[0]
    with pytest.raises(FactoryPanic) as raised:
        build_node(node, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)
    assert raised.value.info.observed == "ClassDef"


def test_metaclass_keyword_is_a_loud_factory_gap() -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse("class C(metaclass=M):\n    pass\n").body[0]
    with pytest.raises(FactoryPanic) as raised:
        build_node(node, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)
    assert raised.value.info.observed == "ClassDef"


def test_function_def_is_not_owned_by_class_def_sugar() -> None:
    assert ClassDefSugar.owns(_site("def f():\n    return 1\n")) is False
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse("def f():\n    return 1\n").body[0]
    result = build_node(node, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)
    assert result.audit_row.selected == "FunctionDefSugar"
