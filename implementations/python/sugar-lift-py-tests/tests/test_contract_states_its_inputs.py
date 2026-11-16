"""A function's contract takes as inputs what its body reads that the caller
supplies at the call, not only its parameters (#7757 step 4).

A captured cell is read when the function is called, from the enclosing
scope the call sees, so the caller supplies it as it supplies an actual: the
contract states it as the formal ``cell:<name>`` after the parameters. A
default the ``def`` statement bound is the formal ``default:<param>``, which
prove's binder binds to a parameter the call omits. A module global a call
reads is the formal ``global:<name>``: the contract is stated over it, and
the row states the value the module's run left, which prove's binder binds
where no call supplies one (step 5). Before this, a lambda or local ``def``
reading an enclosing local was refused by name and its row was
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


def test_a_def_reading_a_module_global_states_it_as_an_input(tmp_path):
    row = _rows(
        tmp_path,
        "G = 3\n\n\ndef f(x):\n    return G\n",
        lambda tree: next(iter(tree.functions())),
    )

    # The body reads ``G`` when ``f`` runs, so the caller supplies it at the
    # call (``py.global``): the contract names it after the parameters.
    assert row.formals == ["x", "global:G"]
    assert len(row.formal_sorts) == 2
    # The contract is stated over the input (step 5): its post reads the free
    # ``global:G``, and the row states the value the module's run left for
    # it, which prove's one binder binds where no call supplies one.
    assert "global:G" in repr(row.post.ir_formula)
    ((formal, term),) = row.input_values
    assert formal == "global:G"
    assert "3" in repr(term)


def test_an_undecided_global_is_an_input_with_no_stated_value(tmp_path):
    row = _rows(
        tmp_path,
        "X = []\n\n\ndef add():\n    X.append(1)\n\n\nadd()\n\n\n"
        "def f():\n    return X\n",
        lambda tree: [fn for fn in tree.functions() if fn.name == "f"][0],
    )

    # ``add()`` may have changed the list ``X`` names, so the module's run
    # leaves ``X`` undecided where ``f`` reads it.  ``f`` is built and its
    # contract is stated over the free ``global:X`` input with no stated
    # value (#8704): a claim that reads it is undecidable by name at prove.
    # Never a refusal of the file, never a value the run does not determine.
    # ``add`` mutates ``X`` through a dispatched call, so every contract that
    # takes ``X`` takes its class too (``class:global:X``, #7757 step 7); with
    # no value stated, no class is stated either.
    assert row.formals == ["global:X", "class:global:X"]
    assert "global:X" in repr(row.post.ir_formula)
    assert row.input_values == ()


def test_a_global_mutated_in_place_states_its_class_beside_its_value(tmp_path):
    row = _rows(
        tmp_path,
        "G = [1]\n\n\ndef bump():\n    G[0] = 2\n",
        lambda tree: next(iter(tree.functions())),
    )

    # ``G[0] = 2`` on the global's object is the dispatched ``__setitem__``
    # over the class of the object ``G`` binds: the contract takes it as
    # ``class:global:G`` after the global itself, and the row states it
    # beside the global's value, the builtin ``list`` the module's run made
    # (#7757 step 7).
    assert row.formals == ["global:G", "class:global:G"]
    stated = dict(row.input_values)
    assert set(stated) == {"global:G", "class:global:G"}
    assert "python:builtin" in repr(stated["class:global:G"])
    assert "list" in repr(stated["class:global:G"])


def test_a_global_only_a_star_import_may_bind_is_an_input_with_no_stated_value(
    tmp_path,
):
    row = _rows(
        tmp_path,
        "from unread_module import *\n\n\ndef f():\n    return undefined_registry\n",
        lambda tree: [fn for fn in tree.functions() if fn.name == "f"][0],
    )

    # Nothing the source spells binds ``undefined_registry``; only the star
    # import may.  It is a module global with no stated value: the free
    # ``global:undefined_registry`` input, read through its undecided key,
    # exactly as a global the module's run leaves undecided (#8802).  Never
    # a bare free variable that refuses the whole function.
    assert row.formals == ["global:undefined_registry"]
    assert "global:undefined_registry" in repr(row.post.ir_formula)
    assert row.input_values == ()


def test_a_class_is_a_definition_never_an_input(tmp_path):
    row = _rows(
        tmp_path,
        "class Box:\n    pass\n\n\ndef f():\n    return Box\n",
        lambda tree: [fn for fn in tree.functions() if fn.name == "f"][0],
    )

    # A class statement binds a definition (decision (c), #7757 step 5):
    # the body reads it at the value the module's run left, as it reads a
    # ``def``'s or an import's name.
    assert row.formals == []
    assert row.input_values == ()


def test_a_global_a_called_function_reads_is_the_caller_s_input(tmp_path):
    row = _rows(
        tmp_path,
        "X = 1\n\n\ndef g():\n    return X\n\n\ndef f():\n    return g()\n",
        lambda tree: [fn for fn in tree.functions() if fn.name == "f"][0],
    )

    # ``g`` reads ``X`` where ``f`` calls it, so ``f``'s call supplies it
    # from ``f``'s own input: a caller of ``f`` while the module runs
    # supplies the binding standing there, never the module-final value.
    assert row.formals == ["global:X"]


def test_recursive_same_file_calls_share_one_set_of_global_inputs(tmp_path):
    from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
    from sugar_source_tree.nodes import _global_input_names

    producer = tmp_path / "producer.py"
    producer.write_text(
        "X = 1\nY = 2\nZ = 3\n\n\n"
        "def f(n):\n    a = X\n    return g(n)\n\n\n"
        "def g(n):\n    b = Y\n    return f(n)\n\n\n"
        "def h():\n    c = Z\n    return f(0)\n"
    )
    tree = open_source_file_for_construction(producer, root=tmp_path)
    by_name = {fn.name: fn for fn in tree.functions()}

    # ``f`` and ``g`` call each other: each contract takes what the other's
    # contract takes, the least answer that holds for both.  ``h`` takes its
    # own read and what ``f``'s contract takes, read off that contract.
    assert _global_input_names(by_name["f"]) == frozenset({"X", "Y"})
    assert _global_input_names(by_name["g"]) == frozenset({"X", "Y"})
    assert _global_input_names(by_name["h"]) == frozenset({"X", "Y", "Z"})


def test_global_inputs_follow_the_defaults_in_name_order(tmp_path):
    row = _rows(
        tmp_path,
        "B = 2\nA = 1\n\n\ndef f(k=0):\n    b = B\n    return A\n",
        lambda tree: next(iter(tree.functions())),
    )

    assert row.formals == ["k", "default:k", "global:A", "global:B"]
    assert len(row.formal_sorts) == 4


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
