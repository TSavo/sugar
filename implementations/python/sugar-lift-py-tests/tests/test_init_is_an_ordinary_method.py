"""An ``__init__`` is an ordinary method (#7757 B2).

Its contract is the method contract any ``def`` states: its receiver is its
first formal, whose class is the ``class:<self>`` input a caller binds (the
class call's dispatched ``__init__`` edge, or ``super().__init__()``), and it
states what it leaves in that object over ``python:after(out, "self")``:
the fields its quiet tail stores, under the plain-store guard (#8862), its
halts (#8961), and what the object's ``__dict__`` may hold where it leaves
(``python:holds_decided`` and ``python:may_hold``, or
``python:class_undecided``), which prove composes with the class row's
``python:type_is`` into the instance a class call makes.
"""

from __future__ import annotations


def _init_row(tmp_path, source):
    from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
    from sugar_lift_py_tests.tree_enumerate import function_contract_rows

    producer = tmp_path / "producer.py"
    producer.write_text(source)
    tree = open_source_file_for_construction(producer, root=tmp_path)
    init = [fn for fn in tree.functions() if fn.name == "__init__"][0]
    _memento, rows = function_contract_rows(init, "producer.py")
    assert rows is not None
    (row,) = rows
    return row


def test_an_init_s_receiver_is_its_formal_with_a_class_input(tmp_path):
    row = _init_row(
        tmp_path,
        "class Box:\n    def __init__(self, n):\n        self.n = n\n",
    )

    assert row.formals[:2] == ["self", "n"]
    assert "class:self" in row.formals
    post = repr(row.post.ir_formula)
    # The field it leaves in ``self``, under the plain-store guard.
    assert "attr:n" in post and "python:plain_store" in post
    # What ``self.__dict__`` may hold where it leaves.
    assert "python:holds_decided" in post
    assert "python:may_hold" in post
    assert "python:class_undecided" in post  # under the guard's complement


def test_an_init_that_hands_self_to_code_leaves_its_dict_undecided(tmp_path):
    row = _init_row(
        tmp_path,
        "class Box:\n"
        "    def __init__(self, n):\n"
        "        self.n = n\n"
        "        self.check()\n"
        "\n"
        "    def check(self):\n"
        "        return None\n",
    )

    post = repr(row.post.ir_formula)
    # ``self.check()`` runs code that may store any field: nothing is decided
    # about what the ``__dict__`` holds.
    assert "python:class_undecided" in post
    assert "python:holds_decided" not in post


def test_a_function_that_is_no_init_states_no_receiver_dict(tmp_path):
    from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
    from sugar_lift_py_tests.tree_enumerate import function_contract_rows

    producer = tmp_path / "producer.py"
    producer.write_text(
        "class Box:\n    def fill(self, n):\n        self.n = n\n"
    )
    tree = open_source_file_for_construction(producer, root=tmp_path)
    fill = [fn for fn in tree.functions() if fn.name == "fill"][0]
    _memento, rows = function_contract_rows(fill, "producer.py")
    (row,) = rows
    post = repr(row.post.ir_formula)
    assert "python:holds_decided" not in post
    assert "python:class_undecided" not in post
