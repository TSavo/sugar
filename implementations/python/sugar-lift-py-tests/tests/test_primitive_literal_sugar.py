from __future__ import annotations

import ast

from factory_reduce import fol, reduce_term

from sugar_lift_py_tests.factory import SourceFragment
from sugar_lift_py_tests.floor import BoolValue, StringValue, SymbolicValue, TermValue
from sugar_lift_py_tests.ir import bool_const, ctor, num, str_const
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.sugar.primitive_literal_sugar import PrimitiveLiteralSugar


def test_primitive_literal_reduces_to_sorted_proofir_consts():
    # the ProofIR end of the reduction: int -> Int const, str -> String const.
    assert fol(reduce_term("42")) == fol(num(42))
    assert fol(reduce_term("'abc'")) == fol(str_const("abc"))


def test_primitive_literal_sugar_is_value_born_from_site() -> None:
    int_node = ast.parse("42", mode="eval").body
    string_node = ast.parse('"abc"', mode="eval").body

    int_sugar = PrimitiveLiteralSugar.from_site(
        SourceFragment.from_node(int_node, "literals.py")
    )
    string_sugar = PrimitiveLiteralSugar.from_site(
        SourceFragment.from_node(string_node, "literals.py")
    )

    assert int_sugar == PrimitiveLiteralSugar(value=42)
    assert string_sugar == PrimitiveLiteralSugar(value="abc")
    assert not hasattr(int_sugar, "node")
    assert not hasattr(string_sugar, "node")
    assert complete_value(int_sugar.desugar(), owner="int literal") == TermValue(42)
    assert complete_value(
        string_sugar.desugar(), owner="string literal"
    ) == StringValue("abc")


def test_none_primitive_literal_sugar_reduces_to_none_ctor() -> None:
    none_node = ast.parse("None", mode="eval").body

    none_sugar = PrimitiveLiteralSugar.from_site(
        SourceFragment.from_node(none_node, "literals.py")
    )

    assert none_sugar == PrimitiveLiteralSugar(value=None)
    assert not hasattr(none_sugar, "node")
    assert complete_value(none_sugar.desugar(), owner="none literal") == SymbolicValue(
        ctor("None", [])
    )


def test_bool_primitive_literal_sugar_reduces_to_bool_floor() -> None:
    bool_node = ast.parse("True", mode="eval").body

    bool_sugar = PrimitiveLiteralSugar.from_site(
        SourceFragment.from_node(bool_node, "literals.py")
    )

    assert bool_sugar == PrimitiveLiteralSugar(value=True)
    assert complete_value(bool_sugar.desugar(), owner="bool literal") == BoolValue(
        True
    )
    assert fol(reduce_term("True")) == fol(bool_const(True))
