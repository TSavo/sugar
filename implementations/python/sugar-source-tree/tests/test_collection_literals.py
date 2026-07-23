"""Collection displays: list, tuple, set, dict -- through the node.

Each reduces its elements and holds them as the collection floor value; the
value owns len/subscript/membership. Spread displays preserve the Python
reference constructors rather than treating a spread as one ordinary element.
"""

import tempfile

import pytest

from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _fn(src: str):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(src)
        path = f.name
    return next(SourceFile(path_source(path)).functions())


def _post_term(src):
    return _fn(src).sugar().desugar().value.post().args[1]


def test_list_tuple_set_dict_construct_their_terms():
    assert _post_term("def A(z):\n    return [1, 2, z]\n").name == "array"
    assert _post_term("def A(z):\n    return (z, 2)\n").name == "tuple"
    assert _post_term("def A(z):\n    return {1, 2, 3}\n").name == "python:set"
    assert _post_term("def A(z):\n    return {1: z, 2: 3}\n").name == "python:dict"


def test_collection_composes_with_a_call():
    # len([z, z, z]) -- the list is a real term inside the call
    term = _post_term("def A(z):\n    return len([z, z, z])\n")
    assert term.name == "call:len"
    assert term.args[0].name == "array" and len(term.args[0].args) == 3


@pytest.mark.parametrize(
    ("expression", "outer"),
    [
        ("[1, *xs]", "python:list"),
        ("(1, *xs)", "python:tuple"),
        ("{1, *xs}", "python:set"),
    ],
)
def test_star_spread_builds_reference_literal_shape(expression, outer):
    term = _post_term(f"def A(xs):\n    return {expression}\n")

    assert term.name == outer
    spread = term.args[-1]
    assert spread.name == "python:starred"
    assert spread.args[0].name == "xs"


def test_double_star_spread_builds_reference_dict_entry():
    term = _post_term("def A(d):\n    return {1: 2, **d}\n")

    assert term.name == "python:dict"
    spread_entry = term.args[-1]
    assert spread_entry.name == "python:dict_entry"
    assert spread_entry.args[0].name == "None"
    assert spread_entry.args[0].args == ()
    assert spread_entry.args[1].name == "d"


def test_literal_spread_discriminates_the_wrapped_value():
    left = _post_term("def A(xs, ys):\n    return [*xs]\n")
    right = _post_term("def A(xs, ys):\n    return [*ys]\n")

    assert left.args[0].name == right.args[0].name == "python:starred"
    assert left.args[0].args[0].name == "xs"
    assert right.args[0].args[0].name == "ys"
    assert left != right


if __name__ == "__main__":
    test_list_tuple_set_dict_construct_their_terms()
    test_collection_composes_with_a_call()
    test_star_spread_builds_reference_literal_shape("[1, *xs]", "python:list")
    test_double_star_spread_builds_reference_dict_entry()
    test_literal_spread_discriminates_the_wrapped_value()
    print("ok: list/tuple/set/dict literals and reference spreads build")
