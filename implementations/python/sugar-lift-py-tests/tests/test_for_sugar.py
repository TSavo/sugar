"""ForSugar: for x in it: body threads over py.iter_elem(it).

Simple-Name target, empty orelse only. Tuple targets and for/else stay loud gaps.
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
from sugar_lift_py_tests.sugar.for_sugar import ForSugar


def _site(source: str):
    node = ast.parse(source).body[0]
    return SourceFragment.from_node(node, "t.py")


def test_for_body_threads_and_binds_iter_elem_coordinate() -> None:
    """(1) Body contributes; loop target is py.iter_elem(iterable)."""
    block = compose_block(
        "    for x in z:\n"
        "        return x\n",
        binds={"z": SymbolicValue(make_var("z"))},
    )
    assert isinstance(block, BlockValue)
    # BlockValue splices the for-body return -- no wrapper residue.
    assert len(block.statements) == 1
    ret = block.statements[0]
    assert isinstance(ret, ReturnValue)
    value = ret.value
    assert isinstance(value, CallSiteValue)
    assert value.target_name == "iter_elem"
    assert value.term == ctor("py.iter_elem", [make_var("z")])


def test_iterable_discriminates_the_iter_elem_coordinate() -> None:
    """(2) Different iterable produces a different element coordinate."""
    for_z = compose_block(
        "    for x in z:\n"
        "        return x\n",
        binds={"z": SymbolicValue(make_var("z"))},
    )
    for_w = compose_block(
        "    for x in w:\n"
        "        return x\n",
        binds={"w": SymbolicValue(make_var("w"))},
    )
    term_z = for_z.statements[0].value.term
    term_w = for_w.statements[0].value.term
    assert term_z == ctor("py.iter_elem", [make_var("z")])
    assert term_w == ctor("py.iter_elem", [make_var("w")])
    assert term_z != term_w


def test_owns_simple_name_for_not_tuple_while_or_expr() -> None:
    """(3) owns simple-Name For; not tuple target, While, or Assign."""
    assert ForSugar.owns(_site("for x in y:\n    pass\n")) is True
    assert ForSugar.owns(_site("for a, b in y:\n    pass\n")) is False
    assert ForSugar.owns(_site("while y:\n    pass\n")) is False
    assert ForSugar.owns(_site("x = 1\n")) is False
    # Non-empty else: not owned this arm.
    assert (
        ForSugar.owns(_site("for x in y:\n    pass\nelse:\n    pass\n")) is False
    )

    catalog = default_catalog()
    simple = _site("for x in y:\n    pass\n")
    tuple_target = _site("for a, b in y:\n    pass\n")
    assert any(
        c.name == "ForSugar"
        for c in catalog.candidates_for(SugarRole.STATEMENT, simple)
    )
    assert not list(catalog.candidates_for(SugarRole.STATEMENT, tuple_target))


def test_tuple_target_for_is_a_loud_factory_gap() -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse("for a, b in y:\n    pass\n").body[0]
    with pytest.raises(FactoryPanic) as raised:
        build_node(node, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)
    assert raised.value.info.observed == "For"


def test_for_else_is_a_loud_factory_gap() -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse("for x in y:\n    pass\nelse:\n    pass\n").body[0]
    with pytest.raises(FactoryPanic) as raised:
        build_node(node, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)
    assert raised.value.info.observed == "For"
