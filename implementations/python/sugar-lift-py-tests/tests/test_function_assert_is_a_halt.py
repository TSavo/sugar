"""An ``assert`` in a function body is a halt of that function (#7757: a halt
is never dropped).

A symbolic ``assert`` states its test as a fact (``InvValue``), the claim of
the function whose body it is.  At a call, prove reads only the callee's
``post`` and its ``panicLoci``; the callee's ``inv`` is its own claim and
never reaches the caller.  So ``def f(n): assert n > 0`` then ``f(-1)``
completed at prove: the ``AssertionError`` was dropped, and the lie that the
call completes could read ``sat``.  Each ``assert`` fact of a completed arm
of the function's own universe is now the split ``if not <test>: raise
AssertionError`` is (``assert_sugar.halts_where_its_asserts_fail``, the one
rule the class call applies to ``__init__`` in place): the function halts
with ``AssertionError`` at the ``assert`` under the fact's complement, a
halted arm its contract states as a panic locus, and the completed arm still
holds the fact, so the assertion stays the function's own claim.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import (
    claim_verdict,
    run_source_through_real_solver,
)


def _contract_row(tmp_path, source, name):
    from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
    from sugar_lift_py_tests.tree_enumerate import function_contract_rows

    producer = tmp_path / "producer.py"
    producer.write_text(source)
    tree = open_source_file_for_construction(producer, root=tmp_path)
    (function,) = [item for item in tree.functions() if item.name == name]
    _memento, rows = function_contract_rows(function, "producer.py")
    assert rows is not None
    (row,) = [row for row in rows if row.kind == "function-contract"]
    return row


def _assertion_loci(row) -> list:
    return [
        locus for locus in row.panic_loci if "AssertionError" in repr(locus.arg_term)
    ]


def test_an_assert_over_a_formal_is_a_panic_locus_of_its_function(tmp_path):
    row = _contract_row(
        tmp_path,
        "def f(n):\n    assert n > 0\n    return n\n",
        "f",
    )

    (locus,) = _assertion_loci(row)
    assert locus.line == 2


def test_the_assert_stays_the_functions_claim(tmp_path):
    # The halt is stated beside the claim, never in place of it: a test
    # function's ``assert`` is still its claim.
    row = _contract_row(
        tmp_path,
        "def f(n):\n    assert n > 0\n    return n\n",
        "f",
    )

    assert row.inv is not None
    assert [locus.line for locus in _assertion_loci(row)] == [2]


def test_two_asserts_are_two_halts(tmp_path):
    row = _contract_row(
        tmp_path,
        "def f(n):\n    assert n > 0\n    assert n < 10\n    return n\n",
        "f",
    )

    assert sorted(locus.line for locus in _assertion_loci(row)) == [2, 3]


def test_a_function_with_no_assert_states_no_assertion_locus(tmp_path):
    row = _contract_row(tmp_path, "def f(n):\n    return n\n", "f")

    assert not _assertion_loci(row)


_CALLED = """\
def f(n):
    assert n > 0
    return n


def test_f():
    ok = False
    try:
        f({actual})
    except AssertionError:
        ok = True
    assert ok == {claim}
"""


@pytest.mark.parametrize(
    ("actual", "truth", "lie"),
    [(-1, "True", "False"), (1, "False", "True")],
    ids=["assert-fails", "assert-holds"],
)
def test_the_call_halts_where_the_callees_assert_fails(
    tmp_path: Path, actual: int, truth: str, lie: str
) -> None:
    """``f(-1)`` raises ``AssertionError`` and ``except AssertionError``
    takes it: the truth (``ok == True``) is ``sat``, and the lie that the
    call completes (``ok == False``) is never ``sat``.  ``f(1)`` completes:
    the truth that it did is ``sat``, the lie that it raised never ``sat``.

    ``f``'s own proof has no caller, so what it owes over ``n`` sits above
    ``test_f``'s ``def`` (line 6) and is set aside for the truth
    (``claim_verdict``), as ``test_assertion_site_rows_twin`` reads
    ``double``'s; the lie is read on every row, owed members included, and
    is never ``sat`` either way."""
    truthful = run_source_through_real_solver(
        tmp_path / "t", _CALLED.format(actual=actual, claim=truth)
    )
    lying = run_source_through_real_solver(
        tmp_path / "l", _CALLED.format(actual=actual, claim=lie)
    )
    claimed = claim_verdict(
        truthful.prove_doc, claims_from_line=6, lift_doc=truthful.lift_doc
    )
    print(
        json.dumps(
            {
                "truthful": truthful.verdict,
                "truthful_claim": claimed,
                "lying": lying.verdict,
                "lying_claim": claim_verdict(
                    lying.prove_doc, claims_from_line=6, lift_doc=lying.lift_doc
                ),
            }
        )
    )
    assert claimed == "sat"
    assert truthful.verdict != "unsat"
    assert lying.verdict != "sat"
    assert (
        claim_verdict(lying.prove_doc, claims_from_line=6, lift_doc=lying.lift_doc)
        != "sat"
    )
