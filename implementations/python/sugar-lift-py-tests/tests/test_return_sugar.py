"""ReturnSugar is a statement sugar: it composes its value expression (built by the
factory) into a ReturnValue, the path's returned outcome. A block carries it; an
absorbed comment never disturbs it; a bare return returns Python's explicit None."""

from __future__ import annotations

from factory_reduce import compose_block

from sugar_lift_py_tests.floor import BlockValue, ReturnValue, SymbolicValue, TermValue
from sugar_lift_py_tests.ir import ctor


def test_return_composes_its_value_into_a_return_outcome():
    assert compose_block("    return 5\n") == BlockValue((ReturnValue(TermValue(5)),))


def test_comment_then_return_absorbs_the_comment():
    assert compose_block('    "doc"\n    return 5\n') == BlockValue(
        (ReturnValue(TermValue(5)),)
    )


def test_bare_return_composes_python_none():
    assert compose_block("    return\n") == BlockValue(
        (ReturnValue(SymbolicValue(ctor("None", []))),)
    )
