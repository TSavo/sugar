"""A function's contract names its ``*args`` and ``**kwargs`` (#7757).

Prove's one binder (``consistency::call_argument_formals``) binds a call's
arguments to a contract's formals.  A call spelled as Python spells it --
``__exit__(m, t, v, tb)`` for ``def __exit__(self, *exc)``, a dispatched
``obj.m(1, 2)`` for ``def m(self, *parts)`` -- fits only when the binder
knows which formal is ``*args`` (the tuple of the positional arguments no
other parameter takes) and which is ``**kwargs`` (the dict of the keyword
arguments no other parameter takes).  The contract states it beside its
formals, ``variadicFormals``, read off each formal's coordinate; a contract
with neither states no key and keeps its bytes.
"""

from __future__ import annotations


def _row(tmp_path, source, name):
    from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
    from sugar_lift_py_tests.tree_enumerate import function_contract_rows

    producer = tmp_path / "producer.py"
    producer.write_text(source)
    tree = open_source_file_for_construction(producer, root=tmp_path)
    node = next(fn for fn in tree.functions() if fn.name == name)
    _memento, rows = function_contract_rows(node, "producer.py")
    assert rows is not None
    (row,) = rows
    return row


def test_a_function_s_contract_names_its_variadic_formals(tmp_path):
    row = _row(tmp_path, "def f(a, *rest, b=1, **kw):\n    return a\n", "f")

    assert row.formals[:4] == ["a", "rest", "b", "kw"]
    assert row.variadic_formals == (("positional", "rest"), ("keyword", "kw"))
    assert row._envelope()["variadicFormals"] == [
        {"kind": "positional", "formal": "rest"},
        {"kind": "keyword", "formal": "kw"},
    ]


def test_a_contract_with_no_variadic_formal_states_no_key(tmp_path):
    row = _row(tmp_path, "def f(a, b=1):\n    return a\n", "f")

    assert row.variadic_formals == ()
    assert "variadicFormals" not in row._envelope()
