"""A comprehension is the evaluation that made it (#7757, step 6).

A symbolic comprehension states its own coordinate in the proof
(``ComprehensionSugar._own_coordinate``).  Keyed on its source occurrence
alone, every evaluation of one comprehension -- two calls of one function,
two items of one loop -- was ONE term, so the true ``f(a) is not f(b)`` read
``unsat``.  Python makes a new list (or set, dict, generator) every time the
expression runs, as it makes a new object every time a class is called
(``constructionEvaluation``, #8592).  The coordinate now carries the
evaluation, ``<kind>(<occurrence>, <evaluation key>)``: the dynamic
occurrence (``occurrence.occurrence_term``) of the reduction running it, and,
for a function's contract, the call prove joins it at.

A generator over a literal iterable stated its member transform as a lambda,
which no term table carries: returned, its mint failed.  It now states the
same coordinate, and its making owes, since it is never consumed where it is
made.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def _sugar(source: str, kind: str):
    """The comprehension sugar of the one ``kind`` node of ``source``."""
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_lift_py_tests.sugar.comprehension_sugar import ComprehensionSugar
    from sugar_source_tree.tree import SourceFile

    tree = SourceFile(
        (
            source,
            "tests/comprehension_per_evaluation_fixture.py",
            blake3_512_of(source.encode()),
        ),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    sugar = next(node for node in tree.nodes() if node.kind == kind).sugar()
    assert isinstance(sugar, ComprehensionSugar), sugar
    return sugar


def test_each_evaluation_of_one_comprehension_is_its_own_coordinate() -> None:
    from sugar_lift_py_tests.occurrence import (
        entered,
        loop_iteration_segment,
        occurrence_term,
    )

    sugar = _sugar("def f(xs):\n    return [x for x in xs]\n", "ListComp")
    loop = "blake3-512:" + "a" * 128
    outside = sugar._own_coordinate()
    with entered(loop_iteration_segment(loop, 0)):
        first = sugar._own_coordinate()
        first_again = sugar._own_coordinate()
    with entered(loop_iteration_segment(loop, 1)):
        second = sugar._own_coordinate()

    # One kind, one occurrence, one more argument: the evaluation.
    for term in (outside, first, second):
        assert term.name == "py.listcomp", term
        occurrence, evaluation = term.args
        assert occurrence == outside.args[0], term
        assert occurrence.name == "python:source-occurrence", term
        assert evaluation.name == "python:occurrence", term
    # Outside every item the key is the bare site.
    assert outside.args[1] == occurrence_term(sugar.site, ())
    # Two items are two lists; one evaluation read twice is one.
    assert first != second
    assert first != outside and second != outside
    assert first == first_again


# ``f`` is joined at prove to each call (#7757 step 9): its comprehension is
# keyed by each call's evaluation where its contract is instantiated.
_LIST = """\
def f(xs):
    return [x for x in xs]


def test_f():
    a = [1]
    b = [2]
    assert {claim}
"""

# A generator over a literal list: never consumed where it is made.
_GENERATOR = """\
def h():
    return (x for x in [1, 2])


def test_h():
    assert {claim}
"""


@pytest.mark.parametrize(
    ("source", "truth"),
    [
        (_LIST, "f(a) is not f(b)"),
        (_LIST, "f(a) is not f(a)"),
        (_GENERATOR, "h() is not h()"),
    ],
)
def test_the_truthful_half_is_never_refuted(
    source: str, truth: str, tmp_path: Path
) -> None:
    # Python: every call makes a new object.  Stated as one term for every
    # call, the truth read ``unsat``.
    result = run_source_through_real_solver(
        tmp_path / "t", source.format(claim=truth)
    )
    assert result.verdict != "unsat"


@pytest.mark.parametrize(
    ("source", "lie"),
    [
        (_LIST, "f(a) is f(b)"),
        (_LIST, "f(a) is f(a)"),
        (_GENERATOR, "h() is h()"),
    ],
)
def test_the_lying_half_is_never_sat(source: str, lie: str, tmp_path: Path) -> None:
    # The coordinate is a value prove does not interpret: reading it owes,
    # so two coordinates the solver may choose equal never make a lie ``sat``.
    result = run_source_through_real_solver(tmp_path / "l", source.format(claim=lie))
    assert result.verdict != "sat"


def test_a_returned_generator_over_a_literal_list_states_no_lambda() -> None:
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_lift_py_tests.ir import _Ctor, _Lambda
    from sugar_lift_py_tests.outcome import Completed
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome
    from sugar_source_tree.nodes import FunctionDef
    from sugar_source_tree.tree import SourceFile

    source = "def h():\n    return (x for x in [1, 2])\n"
    tree = SourceFile(
        (source, "test_witness.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    (function,) = [node for node in tree.nodes() if isinstance(node, FunctionDef)]
    outcome = function_universe_outcome(function)
    (done,) = [arm for arm in outcome.exits if isinstance(arm, Completed)]
    term = done.value.post().args[1]

    def lambdas(node) -> bool:
        if isinstance(node, _Lambda):
            return True
        return isinstance(node, _Ctor) and any(lambdas(arg) for arg in node.args)

    assert term.name == "py.generatorexp", term
    occurrence, evaluation = term.args
    assert occurrence.name == "python:source-occurrence", term
    assert evaluation.name == "python:occurrence", term
    assert not lambdas(term), term
    # Its making owes: nothing at prove decides the generator object.
    assert outcome.owed_items(), outcome
