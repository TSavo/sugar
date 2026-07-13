"""WithSugar: with cm as y substitutes the frozen cm coordinate for y.

Single-item synchronous With only. Multi-item and AsyncWith stay loud gaps.
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
    CallSiteValue,
    ReturnValue,
    SymbolicValue,
)
from sugar_lift_py_tests.ir import ctor, make_var
from sugar_lift_py_tests.sugar.with_sugar import WithSugar


def _site(source: str):
    node = ast.parse(source).body[0]
    return SourceFragment.from_node(node, "t.py")


def test_with_body_threads_and_binds_enter_coordinate() -> None:
    """(1) Body contributes; as-target is call:__enter__(cm)."""
    block = compose_block(
        "    with z as g:\n" "        return g\n",
        binds={"z": SymbolicValue(make_var("z"))},
    )
    assert isinstance(block, BlockValue)
    # BlockValue splices the with-body return -- no wrapper residue.
    assert len(block.statements) == 1
    ret = block.statements[0]
    assert isinstance(ret, ReturnValue)
    value = ret.value
    assert isinstance(value, CallSiteValue)
    assert value.target_name == "__enter__"
    assert value.term == ctor("call:__enter__", [make_var("z")])


def test_context_expression_discriminates_the_enter_coordinate() -> None:
    """(2) Different cm produces a different enter coordinate."""
    with_z = compose_block(
        "    with z as g:\n" "        return g\n",
        binds={"z": SymbolicValue(make_var("z"))},
    )
    with_w = compose_block(
        "    with w as g:\n" "        return g\n",
        binds={"w": SymbolicValue(make_var("w"))},
    )
    term_z = with_z.statements[0].value.term
    term_w = with_w.statements[0].value.term
    assert term_z == ctor("call:__enter__", [make_var("z")])
    assert term_w == ctor("call:__enter__", [make_var("w")])
    assert term_z != term_w


def test_owns_single_item_not_multi_or_plain_expr() -> None:
    """(3) owns single-item with; multi-item stays unowned; not Expr."""
    assert WithSugar.owns(_site("with cm as y:\n    pass\n")) is True
    assert WithSugar.owns(_site("with cm:\n    pass\n")) is True
    assert WithSugar.owns(_site("with a, b:\n    pass\n")) is True
    assert WithSugar.owns(_site("with a as x, b as y:\n    pass\n")) is True
    assert WithSugar.owns(_site("with a as (x, y):\n    pass\n")) is False
    assert WithSugar.owns(_site("x = 1\n")) is False

    catalog = default_catalog()
    single = _site("with cm as y:\n    pass\n")
    multi = _site("with a, b:\n    pass\n")
    assert any(
        c.name == "WithSugar"
        for c in catalog.candidates_for(SugarRole.STATEMENT, single)
    )
    assert [
        candidate.name
        for candidate in catalog.candidates_for(SugarRole.STATEMENT, multi)
    ] == ["WithSugar"]


def test_multi_item_with_is_a_loud_factory_gap() -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse("with a, b:\n    pass\n").body[0]
    with pytest.raises(FactoryPanic) as raised:
        build_node(node, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)
    assert raised.value.info.observed == "With"


def test_with_without_as_still_reduces_context_and_body() -> None:
    # Context expr is not dropped when there is no as-target.
    block = compose_block(
        "    with z:\n" "        return 1\n",
        binds={"z": SymbolicValue(make_var("z"))},
    )
    ret = block.statements[0]
    assert isinstance(ret, ReturnValue)
    from sugar_lift_py_tests.floor import TermValue

    assert ret.value == TermValue(1)


def test_callsite_context_manager_substitutes_coordinate_for_as_name() -> None:
    opaque = CallSiteValue(
        target_name="manager",
        arg_values=(),
        parameters=(),
        term=ctor("call:manager", []),
        body=None,
    )

    outcome = compose_block(
        "    with manager as entered:\n" "        return entered\n",
        binds={"manager": opaque},
    )

    returned = outcome.statements[0]
    assert isinstance(returned, ReturnValue)
    assert returned.value is not opaque
    assert returned.value.target_name == "__enter__"
    assert "call:__enter__" in repr(returned.value)
    assert repr(returned.value.term) != repr(opaque.term)


def test_enter_result_twin_cannot_inherit_bare_manager_coordinate() -> None:
    manager = CallSiteValue(
        target_name="transaction",
        arg_values=(),
        parameters=(),
        term=ctor("call:transaction", []),
        body=None,
    )
    block = compose_block(
        "    with manager as cursor:\n" "        return cursor\n",
        binds={"manager": manager},
    )

    cursor = block.statements[0].value
    assert cursor.term == ctor("call:__enter__", [manager.term])
    assert cursor.term != manager.term


def test_unresolved_exit_contract_keeps_raise_carrying_body_loud() -> None:
    manager = CallSiteValue(
        target_name="manager",
        arg_values=(),
        parameters=(),
        term=ctor("call:manager", []),
        body=None,
    )
    with pytest.raises(FactoryPanic, match="__exit__"):
        compose_block(
            "    with manager:\n" "        raise ValueError('boom')\n",
            binds={"manager": manager},
        )


def test_complex_as_target_is_a_loud_factory_gap() -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse("with cm as (a, b):\n    pass\n").body[0]
    with pytest.raises(FactoryPanic) as raised:
        build_node(node, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)
    assert raised.value.info.observed == "With"
