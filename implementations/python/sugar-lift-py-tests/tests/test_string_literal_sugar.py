from __future__ import annotations

import ast

from sugar_lift_py_tests.factory import SourceSite
from sugar_lift_py_tests.floor import StringValue
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.sugar.string_literal_sugar import StringLiteralSugar


def test_string_literal_sugar_is_value_born_from_site() -> None:
    node = ast.parse('"abc"', mode="eval").body

    sugar = StringLiteralSugar.from_site(SourceSite.from_node(node, "strings.py"))

    assert sugar == StringLiteralSugar(value="abc")
    assert not hasattr(sugar, "node")
    assert complete_value(sugar.desugar(), owner="string literal") == StringValue("abc")
