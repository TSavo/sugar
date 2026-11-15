"""A function's contract takes as inputs what its body reads that the caller
supplies at the call, not only its parameters (#7757 step 4).

A captured cell is read when the function is called, from the enclosing
scope the call sees, so the caller supplies it as it supplies an actual: the
contract states it as the formal ``cell:<name>`` after the parameters. A
default the ``def`` statement bound is the formal ``default:<param>``, which
prove's binder binds to a parameter the call omits. Before this, a lambda or
local ``def`` reading an enclosing local was refused by name and its row was
``undecided`` (#8687).
"""

from __future__ import annotations


def _rows(tmp_path, source, pick):
    from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
    from sugar_lift_py_tests.tree_enumerate import function_contract_rows

    producer = tmp_path / "producer.py"
    producer.write_text(source)
    tree = open_source_file_for_construction(producer, root=tmp_path)
    node = pick(tree)
    _memento, rows = function_contract_rows(node, "producer.py")
    assert rows is not None
    (row,) = rows
    return row


def test_a_lambda_over_a_captured_variable_states_a_contract(tmp_path):
    row = _rows(
        tmp_path,
        "def outer():\n    y = 2\n    return lambda x: y\n",
        lambda tree: next(iter(tree.lambdas())),
    )

    assert row.kind == "function-contract"
    assert row.name == "python:producer.outer.<locals>.<lambda>@3:11"
    assert row.formals == ["x", "cell:y"]
    # One sort per formal, the input's included: a whole signature.
    assert len(row.formal_sorts) == 2
    # The post reads the cell as the input the caller supplies, never the
    # binding the enclosing scope held where the lambda was made.
    assert "cell:y" in repr(row.post.ir_formula)


def test_a_local_def_over_a_captured_variable_states_a_contract(tmp_path):
    row = _rows(
        tmp_path,
        "def outer():\n    y = 2\n    def g(x):\n        return y\n    return g\n",
        lambda tree: [fn for fn in tree.functions() if fn.name == "g"][0],
    )

    assert row.kind == "function-contract"
    assert row.formals == ["x", "cell:y"]
    assert "cell:y" in repr(row.post.ir_formula)


def test_a_default_is_an_input_of_the_contract(tmp_path):
    row = _rows(
        tmp_path,
        "def f(x, k=3):\n    return k\n",
        lambda tree: next(iter(tree.functions())),
    )

    # The body reads the parameter; the binder binds a parameter the call
    # omits to the default the caller supplies.
    assert row.formals == ["x", "k", "default:k"]
    assert len(row.formal_sorts) == 3


def test_a_function_reading_only_its_parameters_states_no_input(tmp_path):
    row = _rows(
        tmp_path,
        "def f(x):\n    return x\n",
        lambda tree: next(iter(tree.functions())),
    )

    assert row.formals == ["x"]


def test_an_input_is_spelled_by_its_kind_and_name():
    from sugar_lift_py_tests.contract_input import (
        ContractInputV1,
        input_formal,
        is_contract_input,
    )

    assert input_formal("cell", "y") == "cell:y"
    assert input_formal("global", "G") == "global:G"
    assert input_formal("default", "k") == "default:k"
    assert is_contract_input("cell:y") and not is_contract_input("y")
    item = ContractInputV1.mint(
        owner_definition_cid="blake3-512:" + "1" * 128,
        input_kind="cell",
        name="y",
        read_cid="blake3-512:" + "2" * 128,
    )
    value = item.value()
    # The input is read as a parameter is: its free formal, carrying its
    # coordinate, so an operation on it waits for the caller's value.
    assert value.formal_coordinate is item.coordinate
    assert item.formal == "cell:y"
