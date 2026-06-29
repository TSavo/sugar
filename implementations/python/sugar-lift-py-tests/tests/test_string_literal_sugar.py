from __future__ import annotations

import ast

from sugar_lift_py_tests.canonicalizer import encode_jcs
from sugar_lift_py_tests.factory import SourceSite
from sugar_lift_py_tests.factory.literal_call_report import _floor_to_term
from sugar_lift_py_tests.floor import StringValue
from sugar_lift_py_tests.ir import str_const, term_to_value
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.sugar.string_literal_sugar import StringLiteralSugar


def test_string_literal_sugar_is_value_born_from_site() -> None:
    node = ast.parse('"abc"', mode="eval").body

    sugar = StringLiteralSugar.from_site(SourceSite.from_node(node, "strings.py"))

    assert sugar == StringLiteralSugar(value="abc")
    assert not hasattr(sugar, "node")
    assert complete_value(sugar.desugar(), owner="string literal") == StringValue("abc")


def test_string_literal_projects_to_string_const() -> None:
    # the ProofIR end of the reduction: the string literal becomes a String const.
    node = ast.parse('"abc"', mode="eval").body
    value = complete_value(
        StringLiteralSugar.from_site(SourceSite.from_node(node, "s.py")).desugar(),
        owner="string literal",
    )
    assert encode_jcs(term_to_value(_floor_to_term(value))) == encode_jcs(
        term_to_value(str_const("abc"))
    )
