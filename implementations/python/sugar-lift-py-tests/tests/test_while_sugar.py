"""WhileSugar: while test: body threads the body; test coordinate is reduced.

Empty-orelse While only. Non-empty else: and For stay loud gaps / other arms.
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
    ReturnValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.sugar.for_sugar import ForSugar
from sugar_lift_py_tests.sugar.while_sugar import WhileSugar


def _site(source: str):
    node = ast.parse(source).body[0]
    return SourceFragment.from_node(node, "t.py")


def test_while_body_threads_into_the_record() -> None:
    """(1) Body statement contributes; test is reduced (method coordinate)."""
    block = compose_block(
        "    while z.ready():\n" "        return 1\n",
        binds={"z": SymbolicValue(make_var("z"))},
    )
    assert isinstance(block, BlockValue)
    # BlockValue splices the while-body return -- no wrapper residue.
    assert len(block.statements) == 1
    ret = block.statements[0]
    assert isinstance(ret, ReturnValue)
    assert ret.value == TermValue(1)


def test_while_test_coordinate_carries_when_body_returns_it() -> None:
    """(1) Test coordinate rides when the body returns the condition name."""
    block = compose_block(
        "    while z:\n" "        return z\n",
        binds={"z": SymbolicValue(make_var("z"))},
    )
    ret = block.statements[0]
    assert isinstance(ret, ReturnValue)
    assert ret.value == SymbolicValue(make_var("z"))


def test_test_or_body_discriminates_the_contribution() -> None:
    """(2) Different test or body produces a different contribution/term."""
    # Different test, body returns the condition name.
    while_z = compose_block(
        "    while z:\n" "        return z\n",
        binds={"z": SymbolicValue(make_var("z"))},
    )
    while_w = compose_block(
        "    while w:\n" "        return w\n",
        binds={"w": SymbolicValue(make_var("w"))},
    )
    assert while_z.statements[0].value == SymbolicValue(make_var("z"))
    assert while_w.statements[0].value == SymbolicValue(make_var("w"))
    assert while_z.statements[0].value != while_w.statements[0].value

    # Different body with the same test shape.
    ret_one = compose_block(
        "    while z:\n" "        return 1\n",
        binds={"z": SymbolicValue(make_var("z"))},
    )
    ret_two = compose_block(
        "    while z:\n" "        return 2\n",
        binds={"z": SymbolicValue(make_var("z"))},
    )
    assert ret_one.statements[0].value == TermValue(1)
    assert ret_two.statements[0].value == TermValue(2)
    assert ret_one.statements[0].value != ret_two.statements[0].value


def test_method_test_is_reduced_before_body() -> None:
    """Test method-call coordinate is built (recognition), not dropped."""
    # Body does not use the test result; reducing the test must still succeed
    # so call:ready(z) is the address a dig lands on.
    block = compose_block(
        "    while z.ready():\n" "        return 1\n",
        binds={"z": SymbolicValue(make_var("z"))},
    )
    assert block.statements[0].value == TermValue(1)
    # MethodCallSugar owns z.ready() as a TERM under the while test build.
    # Smoke: building the While selects WhileSugar, not a gap.
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse("while z.ready():\n    return 1\n").body[0]
    result = build_node(node, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)
    assert result.audit_row.selected == "WhileSugar"


def test_owns_empty_orelse_while_not_for_or_else_or_expr() -> None:
    """(3) owns empty-orelse While; not For, while-else, or Assign."""
    assert WhileSugar.owns(_site("while y:\n    pass\n")) is True
    assert WhileSugar.owns(_site("for x in y:\n    pass\n")) is False
    assert ForSugar.owns(_site("while y:\n    pass\n")) is False
    assert WhileSugar.owns(_site("x = 1\n")) is False
    # Non-empty else: not owned this arm.
    assert WhileSugar.owns(_site("while y:\n    pass\nelse:\n    pass\n")) is False

    catalog = default_catalog()
    simple = _site("while y:\n    pass\n")
    with_else = _site("while y:\n    pass\nelse:\n    pass\n")
    assert any(
        c.name == "WhileSugar"
        for c in catalog.candidates_for(SugarRole.STATEMENT, simple)
    )
    assert not list(catalog.candidates_for(SugarRole.STATEMENT, with_else))


def test_while_else_is_a_loud_factory_gap() -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse("while y:\n    pass\nelse:\n    pass\n").body[0]
    with pytest.raises(FactoryPanic) as raised:
        build_node(node, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)
    assert raised.value.info.observed == "While"


def test_for_is_not_owned_by_while_sugar() -> None:
    # For stays ForSugar's; WhileSugar does not claim it (no false gap on For).
    assert WhileSugar.owns(_site("for x in y:\n    pass\n")) is False
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse("for x in y:\n    pass\n").body[0]
    result = build_node(node, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)
    assert result.audit_row.selected == "ForSugar"
