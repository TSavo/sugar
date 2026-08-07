"""Collection displays: list, tuple, set, dict -- through the node.

Each reduces its elements and holds them as the collection floor value; the
value owns len/subscript/membership. Spread displays use the reference terms.
"""

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.tree import SourceFile


def _fn(src: str):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(src)
        path = f.name
    return next(SourceFile(path_source(path), construction_context=TreeConstructionContextV1.for_test_without_workspace()).functions())


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


def test_star_spread_builds_reference_list_shape():
    term = _post_term("def A(xs):\n    return [1, *xs]\n")
    assert term.name == "python:list"
    assert term.args[1].name == "python:starred"


def test_double_star_spread_builds_reference_dict_shape():
    term = _post_term("def A(d):\n    return {1: 2, **d}\n")
    assert term.name == "python:dict"
    assert term.args[1].name == "python:dict_entry"
    assert term.args[1].args[0].name == "None"


if __name__ == "__main__":
    test_list_tuple_set_dict_construct_their_terms()
    test_collection_composes_with_a_call()
    test_star_spread_builds_reference_list_shape()
    test_double_star_spread_builds_reference_dict_shape()
    print("ok: list/tuple/set/dict literals drained; spreads loud")
