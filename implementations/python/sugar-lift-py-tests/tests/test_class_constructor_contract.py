"""A class states its constructor contract under its join symbol (#7757 step 6).

The owner's ruling of 2026-11-15 ("Edge, join at prove"): a call of a
same-file class is a coordinate and an edge to ``python:<module>.<Class>``,
joined at prove like an imported call. The class's own contract is the
universe of ``return Cls(<formals>)``: its formals are the constructor's
after ``self``, then its inputs. It makes the fresh instance and dispatches
``type(obj).__init__(obj, ...)`` on it (#7757 B3): the ``__init__``'s body is
never applied here, and what it leaves in the instance is its own contract's
(#7757 B2), joined at prove. Each completed arm states the class of the
instance and names it as the ``__init__`` call left it, never its identity
(each call makes a fresh object); each halt of that call is a panic locus of
the class call, so a certain halt reaches a caller through the edge (#8690).
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


def test_a_class_dispatches_its_initializer_on_the_instance_it_makes(tmp_path):
    row = _contract_row(
        tmp_path,
        "class Box:\n    def __init__(self, n):\n        self.n = n\n",
        "Box",
    )

    assert row.name == "python:producer.Box"
    assert row.bridge_source_symbol == "python:producer.Box"
    assert row.formals == ["n"]
    post = repr(row.post.ir_formula)
    # The instance is the ``__init__`` call's receiver as that call left it
    # (``python:after(<call>, "0")``), the term a caller's read of
    # ``Box(3).n`` reaches through the joined ``__init__`` contract.
    assert "call:dispatch:__init__" in post
    assert "python:after" in post
    # The ``__init__``'s body is never read here: no field is stated by the
    # class row itself.
    assert "attr:n" not in post


def test_a_class_states_the_class_of_the_instance_it_makes(tmp_path):
    """Every completed face states the class the construction made the
    instance of (#7757 step 8).  What its ``__dict__`` holds is the
    ``__init__``'s contract's to state; prove composes the two
    (``consistency::initialized_instance``)."""
    row = _contract_row(
        tmp_path,
        "class Box:\n    def __init__(self, n):\n        self.n = n\n",
        "Box",
    )

    post = repr(row.post.ir_formula)
    assert "python:type_is" in post
    assert "python:may_hold" not in post
    assert "python:class_undecided" not in post


def test_a_field_a_class_member_shadows_states_no_read(tmp_path):
    """The class row states no field read at all: a read of a field of the
    result is the ``__init__``'s contract's, under its guards (#7757 B3)."""
    row = _contract_row(
        tmp_path,
        "class Box:\n    def __init__(self, n):\n        self.n = n\n\n"
        "    def n(self):\n        return 0\n",
        "Box",
    )

    post = repr(row.post.ir_formula)
    assert "python:attribute.completes" not in post


def test_a_class_whose_initializer_raises_states_the_halt(tmp_path):
    row = _contract_row(
        tmp_path,
        "class Bad:\n    def __init__(self, n):\n        raise ValueError(n)\n",
        "Bad",
    )

    assert row.name == "python:producer.Bad"
    # The dispatched ``__init__`` call's halted face (its raise, joined at
    # prove), and ``TypeError`` where it returned anything but ``None``.
    assert row.panic_loci


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
