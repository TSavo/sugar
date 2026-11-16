"""An ``assert`` in ``__init__`` is a halt of the construction (#7757: a halt
is never dropped).

A symbolic ``assert`` states its test as a fact: the claim of the function
whose body it is, with no failing arm where it stands (``AssertSugar``).
Each ``assert`` fact of a completed arm of a function's own universe is the
split it is (``assert_sugar.halts_where_its_asserts_fail``, #8961): the
function halts with ``AssertionError`` at the ``assert`` under the fact's
complement, a halted arm its row states as a panic locus.  An ``__init__``
is an ordinary method (#7757 B2), so its asserts are loci of its own row.
The class row never applies ``__init__`` in place (#7757 B3): it makes the
fresh instance and dispatches ``__init__`` on it, an edge whose halts are the
class call's halts, joined at prove to the ``__init__``'s contract.  So
``C(-1)`` over ``assert n > 0`` still never completes at prove.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


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


def _assertion_loci(row) -> list:
    return [
        locus for locus in row.panic_loci if "AssertionError" in repr(locus.arg_term)
    ]


def test_an_initializer_assert_over_a_formal_is_a_panic_locus(tmp_path):
    row = _init_row(
        tmp_path,
        "class C:\n    def __init__(self, n):\n        assert n > 0\n",
    )

    (locus,) = _assertion_loci(row)
    assert locus.line == 3


def test_an_initializer_assert_over_a_field_is_a_panic_locus(tmp_path):
    row = _init_row(
        tmp_path,
        "class C:\n    def __init__(self, n):\n        self.n = n\n"
        "        assert self.n > 0\n",
    )

    assert [locus.line for locus in _assertion_loci(row)] == [4]


def test_an_initializer_assert_is_no_claim_of_the_class(tmp_path):
    # The failing ``assert`` is the ``__init__``'s halt, reached through the
    # class row's dispatched ``__init__`` edge, whose halted face is a halt
    # of the class call; never the class's claim, and never applied here.
    row = _contract_row(
        tmp_path,
        "class C:\n    def __init__(self, n):\n        assert n > 0\n",
        "C",
    )

    assert row.inv is None, row.inv
    assert not _assertion_loci(row)
    assert row.panic_loci
    assert "call:dispatch:__init__" in repr(row.post.ir_formula)


def test_an_initializer_with_no_assert_states_no_assertion_locus(tmp_path):
    row = _init_row(
        tmp_path,
        "class C:\n    def __init__(self, n):\n        self.n = n\n",
    )

    assert not _assertion_loci(row)


_CONSTRUCTED = """\
class C:
    def __init__(self, n):
        assert n > 0


def test_c():
    ok = False
    try:
        C({actual})
        ok = True
    except AssertionError:
        pass
    assert ok == {claim}
"""


@pytest.mark.parametrize(
    ("actual", "truth", "lie"),
    [(-1, "False", "True"), (1, "True", "False")],
    ids=["assert-fails", "assert-holds"],
)
def test_the_construction_halts_where_its_assert_fails(
    tmp_path: Path, actual: int, truth: str, lie: str
) -> None:
    """``C(-1)`` raises ``AssertionError``: the lie that it completes
    (``ok == True``) is never ``sat``, and the truth is never refuted.
    ``C(1)`` completes: the lie that it raised is never ``sat``."""
    truthful = run_source_through_real_solver(
        tmp_path / "t", _CONSTRUCTED.format(actual=actual, claim=truth)
    )
    lying = run_source_through_real_solver(
        tmp_path / "l", _CONSTRUCTED.format(actual=actual, claim=lie)
    )
    print(json.dumps({"truthful": truthful.verdict, "lying": lying.verdict}))
    assert truthful.verdict != "unsat"
    assert lying.verdict != "sat"
