"""The comparison family beyond `==`: `!=`, `<`, `<=`, `>`, `>=`, and chains.

`==` stays EqualityOpSugar; the ordering family routes to the value's floor
method (py.lt/py.le/py.gt/py.ge); `!=` is `==` negated; a chained comparison
`a < b < c` conjoins its adjacent pairs.
"""

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile

from native_carrier_testimony import authenticated_function_value, native_carrier_for


def _inv(src: str):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(src)
        path = f.name
    function = next(SourceFile(path_source(path)).functions())
    # Deleted expectation: an undecided formal equality was already completed.
    return authenticated_function_value(function, operator="equals").invs()[0]


def _carrier(src: str, operator: str):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(src)
        path = f.name
    return native_carrier_for(
        next(SourceFile(path_source(path)).functions()), operator=operator
    )


def test_not_equal_is_equals_negated():
    inv = _inv("def A(z):\n    assert z != 2\n    return z\n")
    assert inv.kind == "not"
    assert inv.operands[0].name == "py.eq"


def test_ordering_operators_emit_their_atoms():
    """Deleted expectation: formal orderings immediately emitted py.lt/le/gt/ge."""
    for spelling, operator, right_value in (
        ("<", "less_than", 10),
        ("<=", "less_equal", 10),
        (">", "greater_than", 0),
        (">=", "greater_equal", 0),
    ):
        carrier = _carrier(
            f"def A(z):\n    assert z {spelling} {right_value}\n    return z\n",
            operator,
        )
        left, right = carrier.operands
        assert left.to_term(owner="ordering carrier tooth").name == "z"
        assert right.value == right_value


def test_chained_comparison_conjoins_adjacent_pairs():
    """Deleted expectation: a formal chain was one completed conjunction."""
    carrier = _carrier("def A(z):\n    assert 0 < z < 10\n    return z\n", "less_than")
    left, right = carrier.operands
    assert left.value == 0
    assert right.to_term(owner="comparison-chain carrier tooth").name == "z"
    assert len(carrier.continuations) == 6


def test_comparison_composes_inside_boolop():
    """Deleted expectation: a formal BoolOp projected a completed conjunction."""
    carrier = _carrier(
        "def A(z):\n    assert (z == 1) and (z != 2)\n    return z\n", "equals"
    )
    left, right = carrier.operands
    assert left.to_term(owner="boolop carrier tooth").name == "z"
    assert right.value == 1
    assert len(carrier.continuations) == 6


if __name__ == "__main__":
    test_not_equal_is_equals_negated()
    test_ordering_operators_emit_their_atoms()
    test_chained_comparison_conjoins_adjacent_pairs()
    test_comparison_composes_inside_boolop()
    print("ok: comparison family drained -- !=, <, <=, >, >=, chains, boolop-composed")
