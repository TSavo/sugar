"""The comparison family beyond `==`: `!=`, `<`, `<=`, `>`, `>=`, and chains.

`==` stays EqualityOpSugar; the ordering family routes to the value's floor
method (py.lt/py.le/py.gt/py.ge); `!=` is `==` negated; a chained comparison
`a < b < c` conjoins its adjacent pairs.

A comparison with a parameter operand waits on no caller: it is the
undecided comparison's two faces where it runs (#7757, audit row NEW-1).
"""

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.tree import SourceFile

from native_carrier_testimony import (
    atoms_named,
    undecided_function_value,
    undecided_outcome,
    undetermined_owners,
)


def _fn(src: str):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(src)
        path = f.name
    return next(SourceFile(path_source(path), construction_context=TreeConstructionContextV1.for_test_without_workspace()).functions())


def _inv(src: str, owner: str):
    return undecided_function_value(_fn(src), owner=owner).invs()[0]


def _compares(outcome):
    """``(op, left, right)`` of each ``python:compare`` a completes atom names."""
    return tuple(
        (operation.args[0].value, operation.args[1], operation.args[2])
        for atom in atoms_named(outcome, "python:compare.completes")
        for operation in atom.args
    )


def test_not_equal_is_equals_negated():
    inv = _inv("def A(z):\n    assert z != 2\n    return z\n", "UndecidedCompare:NotEq")
    assert inv.kind == "not"
    assert inv.operands[0].name == "py.eq"


def test_ordering_operators_emit_their_atoms():
    """A formal ordering is the undecided ordering: its atom completes only
    under ``python:compare.completes`` over the formal and the literal."""
    for spelling, kind, atom, right_value in (
        ("<", "Lt", "py.lt", 10),
        ("<=", "LtE", "py.le", 10),
        (">", "Gt", "py.gt", 0),
        (">=", "GtE", "py.ge", 0),
    ):
        function = _fn(f"def A(z):\n    assert z {spelling} {right_value}\n    return z\n")
        inv = undecided_function_value(
            function, owner=f"UndecidedCompare:{kind}"
        ).invs()[0]
        assert inv.name == atom
        assert inv.args[0].name == "z"
        assert inv.args[1].value == right_value
        compares = _compares(undecided_outcome(function))
        assert {op for op, _left, _right in compares} == {kind}
        assert {(left.name, right.value) for _op, left, right in compares} == {
            ("z", right_value)
        }


def test_chained_comparison_conjoins_adjacent_pairs():
    """Each adjacent pair of ``0 < z < 10`` is its own undecided ordering,
    the second evaluated only after the first completed."""
    outcome = undecided_outcome(_fn("def A(z):\n    assert 0 < z < 10\n    return z\n"))
    assert undetermined_owners(outcome).count("UndecidedCompare:Lt") >= 2
    pairs = {
        (op, getattr(left, "value", getattr(left, "name", None)),
         getattr(right, "value", getattr(right, "name", None)))
        for op, left, right in _compares(outcome)
    }
    assert pairs == {("Lt", 0, "z"), ("Lt", "z", 10)}


def test_comparison_composes_inside_boolop():
    """``(z == 1) and (z != 2)``: each equality is its own undecided
    equality over the formal and its literal."""
    outcome = undecided_outcome(
        _fn("def A(z):\n    assert (z == 1) and (z != 2)\n    return z\n")
    )
    owners = undetermined_owners(outcome)
    assert "UndecidedCompare:Eq" in owners
    assert "UndecidedCompare:NotEq" in owners
    pairs = {
        (op, getattr(left, "name", None), getattr(right, "value", None))
        for op, left, right in _compares(outcome)
    }
    assert pairs == {("Eq", "z", 1), ("NotEq", "z", 2)}


if __name__ == "__main__":
    test_not_equal_is_equals_negated()
    test_ordering_operators_emit_their_atoms()
    test_chained_comparison_conjoins_adjacent_pairs()
    test_comparison_composes_inside_boolop()
    print("ok: comparison family drained -- !=, <, <=, >, >=, chains, boolop-composed")
