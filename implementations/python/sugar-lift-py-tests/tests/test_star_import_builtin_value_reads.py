"""A builtin's name a star import may rebind, read as a value, is the
function's ``global:<name>`` input with no stated value, never the free name
(#7757, carry undecided).

Under ``from m import *`` the lifter withholds the builtin reference: the
star import may bind ``tuple``, or leave the builtin, and the lifter reads no
imported module's names.  A call by the name is the one unanswered call by
its spelling and reads no value.  A value read (``isinstance(keys,
tuple)``, ``return NotImplemented``) was bound by nothing and stayed the free
name, so ``ScopedFormula`` refused the function by it (numpy
``_core/multiarray.py::lexsort`` by ``tuple``, ``_core/numeric.py::roll`` by
``dict``, ``_core/numeric.py::isclose`` by ``complex, float, int``,
``matlib.py::rand`` by ``tuple``, ``_core/defchararray.py`` by ``str`` and
``NotImplemented``).  It is now read through its undecided key, as a global
only a star import may bind is (#8802).
"""

from __future__ import annotations


def _tree(tmp_path, source):
    from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction

    producer = tmp_path / "producer.py"
    producer.write_text(source)
    return open_source_file_for_construction(producer, root=tmp_path)


def _row(tmp_path, source, name):
    from sugar_lift_py_tests.tree_enumerate import function_contract_rows

    tree = _tree(tmp_path, source)
    (node,) = [fn for fn in tree.functions() if fn.name == name]
    _memento, rows = function_contract_rows(node, "producer.py")
    assert rows is not None
    (row,) = rows
    return row


_STAR = "from unread_module import *\n\n\n"


def test_a_builtin_read_as_a_value_under_a_star_import_is_an_input(tmp_path):
    row = _row(
        tmp_path,
        _STAR + "def f(keys):\n    if isinstance(keys, tuple):\n"
        "        return 1\n    return 2\n",
        "f",
    )

    # ``tuple`` is read as a value: the star import may have bound it, so it
    # is the free ``global:tuple`` input, read through its undecided key,
    # with no stated value.  ``isinstance`` is called by its spelling: no
    # input.
    assert row.formals == ["keys", "global:tuple"]
    assert row.input_values == ()


def test_not_implemented_returned_under_a_star_import_is_an_input(tmp_path):
    row = _row(
        tmp_path,
        _STAR + "def f(other):\n    return NotImplemented\n",
        "f",
    )

    assert row.formals == ["other", "global:NotImplemented"]
    assert "global:NotImplemented" in repr(row.post.ir_formula)
    assert row.input_values == ()


def test_a_builtin_only_called_under_a_star_import_takes_no_input(tmp_path):
    from sugar_source_tree.nodes import _global_input_names

    tree = _tree(tmp_path, _STAR + "def g(x):\n    return len(x)\n")
    (g,) = [fn for fn in tree.functions() if fn.name == "g"]

    # A call by the name never reads it as a value: the one unanswered call.
    assert _global_input_names(g) == frozenset()


def test_a_builtin_with_no_star_import_is_the_builtin(tmp_path):
    from sugar_source_tree.nodes import _global_input_names

    tree = _tree(
        tmp_path,
        "def f(keys):\n    if isinstance(keys, tuple):\n        return 1\n"
        "    return 2\n",
    )
    (f,) = [fn for fn in tree.functions() if fn.name == "f"]

    # Nothing may rebind ``tuple``: the read is the builtin, no input.
    assert _global_input_names(f) == frozenset()
    assert not f.unit.star_import_builtin("tuple")


def test_a_builtin_the_module_rebinds_is_no_star_import_builtin(tmp_path):
    tree = _tree(tmp_path, _STAR + "tuple = list\n\n\ndef f():\n    return tuple\n")
    (f,) = [fn for fn in tree.functions() if fn.name == "f"]

    # The module binds ``tuple`` itself: the threading reads that binding.
    assert not f.unit.star_import_builtin("tuple")
