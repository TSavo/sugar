"""A class states its constructor contract under its join symbol (#7757 step 6).

The owner's ruling of 2026-11-15 ("Edge, join at prove"): a call of a
same-file class is a coordinate and an edge to ``python:<module>.<Class>``,
joined at prove like an imported call. The class's own contract is the
universe of ``return Cls(<formals>)``: its formals are the constructor's
after ``self``, then its inputs; each completed arm states the fields the
construction set (``attr:<name>(out) == <value>``), never the instance's
identity (each call makes a fresh object); each halt of ``__init__`` is a
panic locus, so a certain halt reaches a caller through the edge (#8690).
"""

from __future__ import annotations


def _contract_row(tmp_path, source, name):
    from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
    from sugar_lift_py_tests.tree_enumerate import (
        class_contract_rows,
        classes_with_contracts,
    )

    producer = tmp_path / "producer.py"
    producer.write_text(source)
    tree = open_source_file_for_construction(producer, root=tmp_path)
    (cls,) = [item for item in classes_with_contracts(tree) if item.name == name]
    _memento, rows = class_contract_rows(cls, "producer.py")
    assert rows is not None
    (row,) = [row for row in rows if row.kind == "function-contract"]
    return row


def test_a_class_states_the_fields_its_initializer_sets(tmp_path):
    row = _contract_row(
        tmp_path,
        "class Box:\n    def __init__(self, n):\n        self.n = n\n",
        "Box",
    )

    assert row.name == "python:producer.Box"
    assert row.bridge_source_symbol == "python:producer.Box"
    assert row.formals == ["n"]
    post = repr(row.post.ir_formula)
    assert "attr:n" in post
    # The instance's identity is fresh per call: never stated.
    assert "py.object.identity" not in post


def test_a_class_whose_initializer_raises_states_the_halt(tmp_path):
    row = _contract_row(
        tmp_path,
        "class Bad:\n    def __init__(self, n):\n        raise ValueError(n)\n",
        "Bad",
    )

    assert row.name == "python:producer.Bad"
    assert len(row.panic_loci) == 1


def test_a_class_with_no_initializer_states_a_contract_over_no_formal(tmp_path):
    row = _contract_row(tmp_path, "class Plain:\n    pass\n", "Plain")

    assert row.name == "python:producer.Plain"
    assert row.formals == []
    assert not row.panic_loci


def test_a_class_contract_states_its_initializer_inputs(tmp_path):
    row = _contract_row(
        tmp_path,
        "G = 3\n\n\nclass Box:\n    def __init__(self, n, k=2):\n"
        "        self.n = n + G\n",
        "Box",
    )

    assert row.formals == ["n", "k", "default:k", "global:G"]


def test_a_nested_class_states_its_own_contract(tmp_path):
    row = _contract_row(
        tmp_path,
        "class Outer:\n    class Inner:\n        def __init__(self):\n"
        "            self.x = 1\n",
        "Inner",
    )

    assert row.name == "python:producer.Outer.Inner"
