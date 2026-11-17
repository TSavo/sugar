"""Twins: ``enumerate`` over an operand whose pairs no shape decides is the
builtin's one unanswered call, never a refusal of its caller (#7757).

``BuiltinSemanticCallable._enumerate`` built the decided iterator for a
list, a tuple or a finite comprehension this frame holds, and named a stale
list by its identity (the bodiless call, #7757 H8).  Every other call fell to
``FloorValue.callable_application_with``, the construction refusal
(``ComputedCallableSugar``, observed ``BuiltinSemanticCallable``): an operand
that is a formal, an attribute or a call's result (``enumerate(names)``,
``enumerate(df.columns)``, ``enumerate(zip(a, b))``), a ``start`` actual, any
other arity.  The first nine-step lane (d5dcbab5c) refused 40 pandas
functions so, every one an ``enumerate`` of that kind.

Each is now the door the stale list already took
(``_unhandled_construct``): the bodiless call, two faces (``iter`` of the
operand may raise), owed, its halt kept.

A lying claim is never ``sat``; a truthful one is never ``unsat``; and the
function that calls ``enumerate`` states its contract, not a refused member.
Each half goes through ``run_source_through_real_solver``: real ``sugar
mint`` then real ``sugar prove``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import (
    claim_verdict,
    run_source_through_real_solver,
)

_TEST = "def test_f():\n    assert {claim}\n"

# ``name: (source, truthful claim, lying claim)``.  Braces are doubled: the
# source is a ``str.format`` template.
_SHAPES = {
    "enumerate-over-a-formal": (
        "def first(names):\n"
        "    pairs = enumerate(names)\n"
        "    return 1\n"
        "\n"
        "\n" + _TEST,
        "first([5]) == 1",
        "first([5]) == 2",
    ),
    "enumerate-with-a-start": (
        "def first(names):\n"
        "    pairs = enumerate(names, 1)\n"
        "    return 1\n"
        "\n"
        "\n" + _TEST,
        "first([5]) == 1",
        "first([5]) == 2",
    ),
    "enumerate-over-a-call-result": (
        "def first(left, right):\n"
        "    pairs = enumerate(zip(left, right))\n"
        "    return 1\n"
        "\n"
        "\n" + _TEST,
        "first([5], [6]) == 1",
        "first([5], [6]) == 2",
    ),
}


def _claims_line(source: str) -> int:
    for number, line in enumerate(source.splitlines(), start=1):
        if line.startswith("def test_"):
            return number
    raise AssertionError("the source states no test function")


def _refused_owners(lift_doc: dict) -> list:
    return [
        row["reason"]["refused"]["owner"]
        for row in lift_doc.get("ir", [])
        if row.get("kind") == "undecided" and "refused" in (row.get("reason") or {})
    ]


@pytest.mark.parametrize("half", ["truthful", "lying"])
@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_enumerate_of_an_undecided_operand_never_refuses_its_caller(
    tmp_path: Path, shape: str, half: str
) -> None:
    source, truthful, lying = _SHAPES[shape]
    text = source.format(claim=truthful if half == "truthful" else lying)
    native: dict = {}
    exec(text, native)
    if half == "truthful":
        native["test_f"]()
    else:
        with pytest.raises(AssertionError):
            native["test_f"]()
    result = run_source_through_real_solver(tmp_path / shape / half, text)
    assert "ComputedCallableSugar" not in _refused_owners(result.lift_doc), (
        result.lift_doc
    )
    verdict = claim_verdict(
        result.prove_doc,
        claims_from_line=_claims_line(text),
        lift_doc=result.lift_doc,
    )
    if half == "lying":
        assert verdict != "sat", result.prove_doc
    else:
        assert verdict != "unsat", result.prove_doc
