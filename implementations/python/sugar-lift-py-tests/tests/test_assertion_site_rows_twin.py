"""Twins for #7766: every assertion the one reduction evaluated reaches the proof.

Step 7 of the nine. The solver twin differs in one literal. The floor decides
``double(3)`` (a same-file call it constructs), so the truthful assert is held
by the one completed arm and states the decided fact ``true``; the lying assert
halts its only arm at the assertion, no completed arm holds it, and its row
states the OR over nothing: ``false``. Both rows go through real ``sugar mint``
and real ``sugar prove``. What the solver decides here is a constant: the
comparison itself was decided by the floor at lift time.

The row twins pin where an assertion's row comes from: the reduction, never the
source text. In a function that completes, an ``assert`` no arm evaluated has
no row. In a function no arm of which completes, every ``assert`` no arm
reached states the halted arms' guards (``not g`` over each), so a test that
certainly raises is refuted at prove.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import (
    claim_verdict,
    run_source_through_real_solver,
)

_TWIN = (
    "def double(x):\n"
    "    return x + x\n"
    "\n"
    "\n"
    "def test_double():\n"
    "    assert double(3) == {claim}\n"
)

_TRUE = {"kind": "and", "operands": []}
_FALSE = {"kind": "not", "operands": [_TRUE]}


def test_a_decided_assertion_reaches_the_solver(tmp_path: Path) -> None:
    """``test_double``'s claim is decided: the floor applies ``double`` to 3.

    ``double``'s own proof has no caller, so ``x`` has no actual and ``x + x``
    is the operation it owes (``tree_enumerate.as_its_own_proof_states``).
    A source that owes anything is never ``sat`` as a whole (step 8), so the
    truthful half is read on the test function's own claims
    (``witness_harness.claim_verdict``): the member ``double`` owes sits above
    the test function's ``def`` (line 5) and is set aside; everything
    ``test_double`` states or owes is read as ``prove_verdict`` reads it."""
    truthful = run_source_through_real_solver(tmp_path / "t", _TWIN.format(claim=6))
    lying = run_source_through_real_solver(tmp_path / "l", _TWIN.format(claim=7))
    assert truthful.verdict == "open"
    assert truthful.prove_doc["owed"] >= 1
    assert claim_verdict(truthful.prove_doc, claims_from_line=5) == "sat"
    assert lying.verdict == "unsat"


_VENDOR = (
    "def encodeBase64(value):\n"
    '    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"\n'
    "    b0 = ord(value[0])\n"
    "    b1 = ord(value[1])\n"
    "    b2 = ord(value[2])\n"
    "    return (\n"
    "        alphabet[b0 >> 2]\n"
    "        + alphabet[((b0 & 3) << 4) | (b1 >> 4)]\n"
    "        + alphabet[((b1 & 15) << 2) | (b2 >> 6)]\n"
    "        + alphabet[b2 & 63]\n"
    "    )\n"
    "\n"
    "\n"
    "def test_vendor():\n"
    '    assert encodeBase64("abc") == {claim}\n'
)


def test_a_same_module_string_claim_is_decided(tmp_path: Path) -> None:
    """The federation vendor's own test (``examples/python-base64-federation``).

    The floor follows ``encodeBase64("abc")`` into its body and the call
    completes with the decided string. A string ``==`` is stated, never folded
    (``StringValue`` has no ``equals``): the row is ``=(<str>, <str>)``, one
    constraint over two literals, which the solver's theory decides. It was
    refused at prove as vacuous (a lone constraint); the truthful vendor's
    row is discharged and the lying vendor's is unsatisfied. Read on the
    test function's consistency row alone: ``encodeBase64``'s own proof has no
    caller and owes its operations over ``value``, which is not this row."""

    def row_status(claim: str) -> str:
        doc = run_source_through_real_solver(
            tmp_path / claim.strip('"'), _VENDOR.format(claim=claim)
        ).prove_doc
        rows = [
            row
            for row in doc.get("rows") or []
            if row.get("property") == "consistency:python:test_witness.test_vendor"
        ]
        assert len(rows) == 1, doc.get("rows")
        return rows[0].get("status")

    assert row_status('"YWJj"') == "discharged"
    assert row_status('"AAAA"') == "unsatisfied"


_UNBOUND = (
    "from double import double\n"
    "\n"
    "\n"
    "def test_double():\n"
    "    assert double(3) == {claim}\n"
)


def test_an_assertion_about_an_unbound_call_stays_open(tmp_path: Path) -> None:
    """No proof answers ``double``: nothing is staged to import. The claim
    stands on a call coordinate, its row reaches the solver's door, and the
    truthful and the lying claim are both left open. An unbound edge is never
    a discharge (#3896)."""
    truthful = run_source_through_real_solver(tmp_path / "t", _UNBOUND.format(claim=6))
    lying = run_source_through_real_solver(tmp_path / "l", _UNBOUND.format(claim=7))
    assert truthful.verdict == "open"
    assert lying.verdict == "open"


_SIBLING_CLAIMS = {
    "two_calls": (
        "from vend import f, g\n"
        "\n"
        "\n"
        "def test_two_calls():\n"
        "    assert f(1) == 2\n"
        "    assert g(1) == 3\n"
    ),
    "one_result_twice": (
        "from vend import f\n"
        "\n"
        "\n"
        "def test_one_result_twice():\n"
        "    y = f(1)\n"
        "    assert y is not None\n"
        "    assert y == 3\n"
    ),
    "two_bounds": (
        "from vend import f\n"
        "\n"
        "\n"
        "def test_two_bounds():\n"
        "    y = f(1)\n"
        "    assert y < 10\n"
        "    assert y < 5\n"
    ),
}


@pytest.mark.parametrize("shape", sorted(_SIBLING_CLAIMS))
def test_sibling_claims_about_unbound_calls_stay_open(
    tmp_path: Path, shape: str
) -> None:
    """Two claims that agree with each other are satisfiable, and satisfiable
    is not proven: nothing is staged to answer ``f`` or ``g``. One function's
    assertion rows are judged together, so a second claim must not stand in
    for the proof the first one lacks (#3896).

    These are open today because every solver seat reports inability on the
    row (z3 exits 1 on the script emitted for it). That is an accident of the
    encoding, not the rule. This twin holds the line when the row compiles.
    """
    result = run_source_through_real_solver(tmp_path / shape, _SIBLING_CLAIMS[shape])
    assert result.verdict == "open"


def _wire_rows(tmp_path: Path, source: str) -> list[dict]:
    """Every row the one function of ``source`` emits, on the wire: exactly
    one, its contract (a function is one contract under one name)."""
    from sugar_lift_py_tests import lift_rpc
    from sugar_lift_py_tests.ir import TermTableBuilder
    from sugar_lift_py_tests.tree_enumerate import function_contract_rows

    (tmp_path / "m.py").write_text(source, encoding="utf-8")
    from sugar_source_tree.reporter import CollectingReporter

    tree = lift_rpc.open_source_file_for_construction(
        tmp_path / "m.py", root=tmp_path, reporter=CollectingReporter()
    )
    (function,) = tuple(tree.functions())
    _memento, rows = function_contract_rows(function, "m.py")
    table = TermTableBuilder()
    wire = [row.to_rpc_with_term_table(table) for row in rows]
    assert [row["kind"] for row in wire] == ["function-contract"], wire
    return wire


def _assertion_lines(row: dict) -> list[int]:
    """The lines of the assertions a contract row states: its assertion
    warrants (every warrant after the definition's own)."""
    return sorted(
        {warrant["span"]["start_line"] for warrant in row["sourceWarrants"][1:]}
    )


def _assertion_rows(tmp_path: Path, source: str) -> list[tuple[int, dict]]:
    """(line, inv) of the assertions the one function of ``source`` states:
    each assertion's line with the contract's ``inv``. Every caller here has
    at most one assertion, so its ``inv`` is that assertion's claim."""
    (row,) = _wire_rows(tmp_path, source)
    if "inv" not in row:
        assert _assertion_lines(row) == [], row
        return []
    return [(line, row["inv"]) for line in _assertion_lines(row)]


def test_a_function_with_two_assertions_is_one_contract(tmp_path: Path) -> None:
    """A function is one contract, never a function-contract beside a second
    ``contract`` under the same name (which prove refused as a duplicate
    contract name and then checked against the copy it dropped). Twin: one
    assertion and two. Both are one row; the second states both assertions
    in its one ``inv``."""
    one = (
        "from vend import f\n"
        "\n"
        "\n"
        "def test_one():\n"
        "    assert f(1) == 2\n"
    )
    two = (
        "from vend import f, g\n"
        "\n"
        "\n"
        "def test_two():\n"
        "    assert f(1) == 2\n"
        "    assert g(1) == 3\n"
    )
    (tmp_path / "one").mkdir()
    (tmp_path / "two").mkdir()
    (single,) = _wire_rows(tmp_path / "one", one)
    (double,) = _wire_rows(tmp_path / "two", two)
    assert single["name"] == "python:m.test_one"
    assert double["name"] == "python:m.test_two"
    assert _assertion_lines(single) == [5]
    assert _assertion_lines(double) == [5, 6]
    assert "post" in single and "inv" in single
    assert "post" in double
    assert double["inv"]["kind"] == "and"
    assert len(double["inv"]["operands"]) >= 2


def test_every_halted_arm_states_a_panic_locus(tmp_path: Path) -> None:
    """A halt is never dropped (#7766, ruling 3). Twin: one literal apart.
    The held ``assert`` leaves no halted arm and the contract states no
    locus; the halted one states one locus in the existing panic-locus shape,
    at the assertion, with exactly the fields the verifier reads."""
    from sugar_lift_py_tests.kit_rpc.body_universe_dto import RUNTIME_FAILURE_SITE

    (held, *_rows) = _wire_rows(tmp_path, "def f():\n    y = 1\n    assert 2 == 2\n")
    (halted, *_rows) = _wire_rows(tmp_path, "def f():\n    y = 1\n    assert 2 == 3\n")
    assert "panicLoci" not in held
    (locus,) = halted["panicLoci"]
    assert set(locus) == {"callee", "file", "line", "argTerm", "guard"}
    assert locus["callee"] == RUNTIME_FAILURE_SITE
    assert (locus["file"], locus["line"]) == ("m.py", 3)
    assert locus["argTerm"]["kind"] == "term-ref"
    assert locus["guard"] == _TRUE


def test_a_halted_arm_states_its_guard_as_path_condition(tmp_path: Path) -> None:
    """Ruling 3: the locus is filled from the reduction (site, raised type,
    guard as path condition). Twin: the same ``assert`` under a branch the
    floor decided, and under a branch on a formal. The first halts under
    truth; the second only under its branch's condition. Every halt states the
    site it halted at."""
    decided = _wire_rows(
        tmp_path, "def f(x):\n    if 1 == 1:\n        assert 2 == 3\n    return 4\n"
    )[0]
    branched = _wire_rows(
        tmp_path, "def f(x):\n    if x == 1:\n        assert 2 == 3\n    return 4\n"
    )[0]
    (unconditional,) = [loc for loc in decided["panicLoci"] if loc["line"] == 3]
    (conditional,) = [loc for loc in branched["panicLoci"] if loc["line"] == 3]
    assert unconditional["guard"] == _TRUE
    assert conditional["guard"] != _TRUE
    for locus in (*decided["panicLoci"], *branched["panicLoci"]):
        assert {"file", "line", "guard"} <= set(locus)


def test_a_function_that_only_halts_claims_nothing(tmp_path: Path) -> None:
    """The post is the conjunction over completed arms only. With no completed
    arm it is the empty conjunction, which says nothing about any result; the
    halt is stated as its panic locus, not folded into the post."""
    (row, *_rows) = _wire_rows(tmp_path, "def f():\n    assert 2 == 3\n")
    assert row["post"] == _TRUE
    (locus,) = row["panicLoci"]
    assert (locus["file"], locus["line"]) == ("m.py", 2)


def test_an_assert_the_reduction_halted_at_states_false(tmp_path: Path) -> None:
    """Twin: the same two statements, one literal apart."""
    held = _assertion_rows(tmp_path, "def f():\n    y = 1\n    assert 2 == 2\n")
    halted = _assertion_rows(tmp_path, "def f():\n    y = 1\n    assert 2 == 3\n")
    assert held == [(3, _TRUE)]
    assert halted == [(3, _FALSE)]


def test_an_assert_no_arm_evaluated_has_no_row(tmp_path: Path) -> None:
    """A handler that never runs and a branch the floor decided away hold
    asserts the reduction never reached. They state nothing: a row there would
    refute a function that is correct. Twin: the same ``assert`` where the
    reduction does reach it."""
    dead_handler = _assertion_rows(
        tmp_path,
        "def f():\n"
        "    try:\n"
        "        y = 1\n"
        "    except Exception:\n"
        "        assert 2 == 3\n"
        "    assert y == 1\n",
    )
    assert dead_handler == [(6, _TRUE)]

    dead_branch = _assertion_rows(
        tmp_path,
        "def f():\n    if 1 == 2:\n        assert 2 == 3\n    return 4\n",
    )
    assert dead_branch == []

    live_branch = _assertion_rows(
        tmp_path,
        "def f():\n    if 1 == 1:\n        assert 2 == 3\n    return 4\n",
    )
    assert live_branch == [(3, _FALSE)]


def test_a_fact_held_before_a_later_halt_is_not_refuted(tmp_path: Path) -> None:
    """The row blames the assertion the reduction halted at, not the ones the
    halted arm had already passed."""
    rows = _assertion_rows(tmp_path, "def f():\n    assert 1 == 1\n    assert 2 == 3\n")
    assert rows == [(3, _FALSE)]


def test_an_assert_after_a_certain_halt_states_the_halting_guards(
    tmp_path: Path,
) -> None:
    """No arm completes, so no completed arm reaches the ``assert``: its row
    is the conjunction over the halted arms of ``not g``. One halt under
    truth folds to ``false``. Twin: one statement apart."""
    completes = _assertion_rows(tmp_path, "def f():\n    y = 1\n    assert 1 == 1\n")
    halts = _assertion_rows(
        tmp_path, "def f():\n    raise ValueError('no')\n    assert 1 == 1\n"
    )
    assert completes == [(3, _TRUE)]
    assert halts == [(3, _FALSE)]


def test_an_assert_passed_before_a_certain_halt_states_no_row(tmp_path: Path) -> None:
    """The halted arm held the first ``assert`` on its way to the halt: that
    one rode its record and is not refuted. Only the one no arm reached
    states the halting guards."""
    rows = _assertion_rows(
        tmp_path,
        "def f():\n    assert 1 == 1\n    raise ValueError('no')\n    assert 2 == 2\n",
    )
    assert rows == [(4, _FALSE)]


_CERTAIN_HALT = (
    "def boom():\n"
    "{body}\n"
    "\n"
    "\n"
    "def test_boom():\n"
    "    boom()\n"
    "    assert 1 == 1\n"
)


def test_a_test_that_certainly_raises_is_refuted(tmp_path: Path) -> None:
    """A twin's verdict answers "does the test pass". The floor decides
    ``boom()`` (a same-file call it constructs). Truthful: it returns, the
    ``assert`` holds on the one completed arm. Lying: it always raises, the
    test function's every arm halts before the ``assert``, and its row states
    the halt's guard ``true`` negated: ``false``. Twin: one statement apart."""
    truthful = run_source_through_real_solver(
        tmp_path / "t", _CERTAIN_HALT.format(body="    return None")
    )
    lying = run_source_through_real_solver(
        tmp_path / "l", _CERTAIN_HALT.format(body="    raise ValueError('no')")
    )
    assert truthful.verdict == "sat"
    assert lying.verdict == "unsat"


def _refused_row(seat_state: str) -> dict:
    return {
        "property": "consistency:test_double",
        "status": "refused",
        "verification": {
            "solverInvocations": [
                {"solver": "z3", "seatState": seat_state},
                {"solver": "cvc5", "seatState": seat_state},
            ]
        },
    }


def test_a_solver_that_could_not_start_is_an_error_not_open() -> None:
    """``open`` is a verdict about the claim. Twin: the same refused row, with
    the seats' state the one thing changed. A seat that ran and could not
    decide leaves the claim open; a seat that could not be started reached no
    verdict at all, and reading that as ``open`` would let a broken machine
    pass every twin that expects ``open``."""
    from sugar_lift_py_tests.witness_harness import (
        WitnessPipelineError,
        prove_verdict,
    )

    assert prove_verdict({"rows": [_refused_row("inability")]}) == "open"
    with pytest.raises(WitnessPipelineError) as failure:
        prove_verdict({"rows": [_refused_row("unavailable")]})
    assert "solver seat unavailable" in str(failure.value)
    assert "cvc5, z3" in str(failure.value)
