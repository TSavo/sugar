from __future__ import annotations

import ast

from sugar_lift_py_tests.factory import SourceFragment
from sugar_lift_py_tests.floor import ArrayLiteral, TermValue
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.sugar.range_sugar import RangeSugar


def test_range_sugar_is_value_born_from_site() -> None:
    node = ast.parse("range(1, 4)", mode="eval").body

    sugar = RangeSugar.from_site(SourceFragment.from_node(node, "ranges.py"))

    assert sugar == RangeSugar(start=1, stop=4)
    assert not hasattr(sugar, "call")
    assert complete_value(sugar.desugar(), owner="range") == ArrayLiteral(
        (TermValue(1), TermValue(2), TermValue(3))
    )
