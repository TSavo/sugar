"""The comparison family beyond `==`: `!=`, `<`, `<=`, `>`, `>=`, and chains.

`==` stays EqualityOpSugar; the ordering family routes to the value's floor
method (py.lt/py.le/py.gt/py.ge); `!=` is `==` negated; a chained comparison
`a < b < c` conjoins its adjacent pairs.
"""

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile


def _inv(src: str):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(src)
        path = f.name
    return (
        next(SourceFile(path_source(path)).functions())
        .sugar()
        .desugar()
        .value.invs()[0]
    )


def test_not_equal_is_equals_negated():
    inv = _inv("def A(z):\n    assert z != 2\n    return z\n")
    assert inv.kind == "not"
    assert inv.operands[0].name == "py.eq"


def test_ordering_operators_emit_their_atoms():
    assert _inv("def A(z):\n    assert z < 10\n    return z\n").name == "py.lt"
    assert _inv("def A(z):\n    assert z <= 10\n    return z\n").name == "py.le"
    assert _inv("def A(z):\n    assert z > 0\n    return z\n").name == "py.gt"
    assert _inv("def A(z):\n    assert z >= 0\n    return z\n").name == "py.ge"


def test_chained_comparison_conjoins_adjacent_pairs():
    # 0 < z < 10  ->  (0 < z) and (z < 10)
    inv = _inv("def A(z):\n    assert 0 < z < 10\n    return z\n")
    assert inv.kind == "and"
    left, right = inv.operands
    assert left.name == "py.lt" and left.args[0].value == 0 and left.args[1].name == "z"
    assert (
        right.name == "py.lt"
        and right.args[0].name == "z"
        and right.args[1].value == 10
    )


def test_comparison_composes_inside_boolop():
    # the case that was blocked before: (z == 1) and (z != 2)
    inv = _inv("def A(z):\n    assert (z == 1) and (z != 2)\n    return z\n")
    assert inv.kind == "and"
    assert inv.operands[0].name == "py.eq"
    assert inv.operands[1].kind == "not"  # z != 2


if __name__ == "__main__":
    test_not_equal_is_equals_negated()
    test_ordering_operators_emit_their_atoms()
    test_chained_comparison_conjoins_adjacent_pairs()
    test_comparison_composes_inside_boolop()
    print("ok: comparison family drained -- !=, <, <=, >, >=, chains, boolop-composed")
