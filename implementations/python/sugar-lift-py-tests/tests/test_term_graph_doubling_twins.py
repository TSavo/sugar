"""Twins from the shapes #9151's bound refused (#7757).

pandas and numpy test functions such as ``test_shape_base.test_unstack`` and
``test_unicode.content_check`` run a value through a run of conditionals whose
arms share it: ``if c: x = x + k`` reduces to ``py.conditional(c, x + k, x)``,
whose first arm contains its second, so the term written out doubles per
statement while its graph grows by a few rows.  #9151 refused 294 of them by
the size written out.  The proof now carries the graph: the definition is
stated, minted and read, never refused for its expansion.

The verifier's laws read terms written out up to a bound; past it a term stays
shared to the solver and the solver seam leaves the formula undecided by name
(``solvers::plan::shares_term_graph``).  So whatever the verdict, a lie is
never ``sat`` and a truth is never ``unsat``, and no claim is dropped.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import (
    claim_verdict,
    run_source_through_real_solver,
)

_LEVELS = 26


def _additive_chain() -> str:
    lines = ["def chain(c):", "    x = 0"]
    for level in range(1, _LEVELS + 1):
        lines.append("    if c:")
        lines.append(f"        x = x + {level}")
    lines.append("    return x")
    return "\n".join(lines) + "\n\n\n"


def _string_chain() -> str:
    lines = ["def chain(c):", "    s = ''"]
    for level in range(_LEVELS):
        lines.append("    if c:")
        lines.append(f"        s = s + {chr(ord('a') + level)!r}")
    lines.append("    return s")
    return "\n".join(lines) + "\n\n\n"


_ADDITIVE_TRUTH = sum(range(1, _LEVELS + 1))
_STRING_TRUTH = "".join(chr(ord("a") + level) for level in range(_LEVELS))

# name -> (helper, truthful claim, lying claim)
_SHAPES = {
    "additive": (
        _additive_chain(),
        f"chain(True) == {_ADDITIVE_TRUTH}",
        f"chain(True) == {_ADDITIVE_TRUTH + 1}",
    ),
    "string": (
        _string_chain(),
        f"chain(True) == {_STRING_TRUTH!r}",
        f"chain(True) == {(_STRING_TRUTH + 'z')!r}",
    ),
}


def _refused_by_the_bound(lift_doc: dict) -> list[dict]:
    return [
        row
        for row in lift_doc.get("ir") or []
        if isinstance(row, dict)
        and row.get("kind") == "undecided"
        and ((row.get("reason") or {}).get("refused") or {}).get("owner")
        == "tree_enumerate.stated_definition_bound"
    ]


@pytest.mark.parametrize("name", sorted(_SHAPES))
def test_a_doubling_chain_lie_is_never_sat_and_truth_never_unsat(
    name: str, tmp_path: Path
) -> None:
    helper, truthful, lying = _SHAPES[name]
    head = helper + "def test_it():\n"
    test_line = head.count("\n")

    truthful_run = run_source_through_real_solver(
        tmp_path / "t", head + f"    assert {truthful}\n"
    )
    lying_run = run_source_through_real_solver(
        tmp_path / "l", head + f"    assert {lying}\n"
    )

    # The graph is carried: the helper is stated, never refused for the size
    # of its term written out (2**26 copies of its start).
    assert _refused_by_the_bound(truthful_run.lift_doc) == []
    assert _refused_by_the_bound(lying_run.lift_doc) == []

    truth = claim_verdict(truthful_run.prove_doc, claims_from_line=test_line)
    lie = claim_verdict(lying_run.prove_doc, claims_from_line=test_line)
    assert truth != "unsat", truth
    assert lie != "sat", lie
