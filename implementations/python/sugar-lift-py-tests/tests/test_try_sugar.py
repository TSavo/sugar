"""TrySugar: try/except threads body + guarded handlers with py.except(type).

Owned: Try with one+ single-type except handlers, no else/finally.
Loud: bare except, else, finally. Multi-type except (A, B) is owned.
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
    TermValue,
)
from sugar_lift_py_tests.ir import ctor, str_const
from sugar_lift_py_tests.sugar.try_sugar import TrySugar


def _site(source: str):
    node = ast.parse(source).body[0]
    return SourceFragment.from_node(node, "t.py")


def test_try_body_and_except_thread_with_caught_type() -> None:
    """(1) Try-body return contributes; except as-name is py.except(Type)."""
    block = compose_block(
        "    try:\n"
        "        return 1\n"
        "    except ValueError as e:\n"
        "        return e\n"
    )
    assert isinstance(block, BlockValue)
    # Try body return + handler return both splice into the record.
    assert len(block.statements) == 2
    first = block.statements[0]
    assert isinstance(first, ReturnValue)
    assert first.value == TermValue(1)
    second = block.statements[1]
    assert isinstance(second, ReturnValue)
    value = second.value
    assert isinstance(value, CallSiteValue)
    assert value.target_name == "except"
    assert value.term == ctor("py.except", [str_const("ValueError")])


def test_handler_type_discriminates_the_except_coordinate() -> None:
    """(2) Different caught type produces a different py.except coordinate."""
    ve = compose_block(
        "    try:\n"
        "        return 1\n"
        "    except ValueError as e:\n"
        "        return e\n"
    )
    te = compose_block(
        "    try:\n"
        "        return 1\n"
        "    except TypeError as e:\n"
        "        return e\n"
    )
    term_ve = ve.statements[1].value.term
    term_te = te.statements[1].value.term
    assert term_ve == ctor("py.except", [str_const("ValueError")])
    assert term_te == ctor("py.except", [str_const("TypeError")])
    assert term_ve != term_te


def test_owns_typed_except_not_bare_else_finally_or_tuple() -> None:
    """(3) owns simple try/except Type; leaves loud shapes unowned."""
    assert (
        TrySugar.owns(
            _site("try:\n    pass\nexcept ValueError:\n    pass\n")
        )
        is True
    )
    assert (
        TrySugar.owns(
            _site("try:\n    pass\nexcept ValueError as e:\n    pass\n")
        )
        is True
    )
    assert TrySugar.owns(_site("try:\n    pass\nexcept:\n    pass\n")) is False
    assert (
        TrySugar.owns(
            _site("try:\n    pass\nexcept (ValueError, TypeError):\n    pass\n")
        )
        is True
    )
    assert (
        TrySugar.owns(
            _site("try:\n    pass\nexcept ValueError:\n    pass\nelse:\n    pass\n")
        )
        is False
    )
    assert (
        TrySugar.owns(
            _site(
                "try:\n    pass\nexcept ValueError:\n    pass\nfinally:\n    pass\n"
            )
        )
        is False
    )
    assert TrySugar.owns(_site("x = 1\n")) is False

    catalog = default_catalog()
    simple = _site("try:\n    pass\nexcept ValueError:\n    pass\n")
    bare = _site("try:\n    pass\nexcept:\n    pass\n")
    assert any(
        c.name == "TrySugar"
        for c in catalog.candidates_for(SugarRole.STATEMENT, simple)
    )
    assert not list(catalog.candidates_for(SugarRole.STATEMENT, bare))


def test_bare_except_is_a_loud_factory_gap() -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse("try:\n    pass\nexcept:\n    pass\n").body[0]
    with pytest.raises(FactoryPanic) as raised:
        build_node(node, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)
    assert raised.value.info.observed == "Try"


def test_try_finally_is_a_loud_factory_gap() -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse(
        "try:\n    pass\nexcept ValueError:\n    pass\nfinally:\n    pass\n"
    ).body[0]
    with pytest.raises(FactoryPanic) as raised:
        build_node(node, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)
    assert raised.value.info.observed == "Try"


def test_try_else_is_a_loud_factory_gap() -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse(
        "try:\n    pass\nexcept ValueError:\n    pass\nelse:\n    pass\n"
    ).body[0]
    with pytest.raises(FactoryPanic) as raised:
        build_node(node, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)
    assert raised.value.info.observed == "Try"
