"""Twins for #7766: every assertion the one reduction evaluated reaches the proof.

Step 7 of the nine. The solver twin differs in one literal. The floor decides
``double(3)`` (a same-file call it constructs), so the truthful assert is held
by the one completed arm and states the decided fact ``true``; the lying assert
halts its only arm at the assertion, no completed arm holds it, and its row
states the OR over nothing: ``false``. Both rows go through real ``sugar mint``
and real ``sugar prove``. What the solver decides here is a constant: the
comparison itself was decided by the floor at lift time.

The row twins pin where an assertion's row comes from: the reduction, never the
source text. An ``assert`` no arm evaluated has no row.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import run_source_through_real_solver

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
    truthful = run_source_through_real_solver(tmp_path / "t", _TWIN.format(claim=6))
    lying = run_source_through_real_solver(tmp_path / "l", _TWIN.format(claim=7))
    assert truthful.verdict == "sat"
    assert lying.verdict == "unsat"


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


def _assertion_rows(tmp_path: Path, source: str) -> list[tuple[int, dict]]:
    """(line, inv) of every assertion row the one function of ``source`` emits."""
    from sugar_lift_py_tests import lift_rpc
    from sugar_lift_py_tests.ir import TermTableBuilder
    from sugar_lift_py_tests.tree_enumerate import function_contract_rows

    (tmp_path / "m.py").write_text(source, encoding="utf-8")
    tree = lift_rpc._open_enumerated_file(
        tmp_path / "m.py", root=tmp_path, locus_root=tmp_path
    )
    (function,) = tuple(tree.functions())
    _memento, rows = function_contract_rows(function, "m.py")
    table = TermTableBuilder()
    wire = [row.to_rpc_with_term_table(table) for row in rows]
    assert wire[0]["kind"] == "function-contract"
    return [
        (row["sourceWarrants"][0]["span"]["start_line"], row["inv"]) for row in wire[1:]
    ]


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


def test_a_re_exported_name_is_not_bridged_by_its_vendors_proof(tmp_path: Path) -> None:
    """OWED, and pinned so it cannot go green by accident.

    The vendor defines ``f`` in ``pkg/_impl.py`` and re-exports it from
    ``pkg/__init__.py``. The consumer imports ``f`` from ``pkg``, so its edge
    carries the demand's symbol, what its own source wrote: ``python:pkg.f``.
    The vendor's contract states ``python:pkg._impl.f``. Step 9 joins an edge
    to a contract by string equality of those two symbols, so with the
    vendor's proof staged the claim is still not bridged: ``open`` on both
    halves. There is no alias table and no second lookup, by ruling: how a
    vendor's proof states what it exports is a question about step 9's text.
    """
    import json
    import shutil

    from sugar_lift_py_tests.witness_harness import (
        _stage_cli_project,
        mint_project,
        prove_verdict,
        run_sugar_cli,
    )

    vendor = tmp_path / "vendor"
    _stage_cli_project(vendor, "def f(x):\n    return x\n")
    (vendor / "pkg").mkdir()
    (vendor / "test_witness.py").rename(vendor / "pkg" / "_impl.py")
    (vendor / "pkg" / "__init__.py").write_text(
        "from pkg._impl import f\n", encoding="utf-8"
    )
    minted = mint_project(vendor)
    assert minted.returncode == 0, minted.stderr
    (vendor_proof,) = sorted(vendor.glob("*.proof"))

    def verdict(claim: int) -> str:
        consumer = tmp_path / f"consumer-{claim}"
        _stage_cli_project(
            consumer,
            f"from pkg import f\n\n\ndef test_f():\n    assert f(3) == {claim}\n",
        )
        imports = consumer / ".sugar" / "imports"
        imports.mkdir(parents=True)
        shutil.copy(vendor_proof, imports / vendor_proof.name)
        minted = mint_project(consumer)
        assert minted.returncode == 0, minted.stderr
        prove = run_sugar_cli(consumer, ["prove", ".", "--json", "--z3", "z3"])
        return prove_verdict(json.loads(prove.stdout))

    assert verdict(3) == "open"
    assert verdict(4) == "open"
