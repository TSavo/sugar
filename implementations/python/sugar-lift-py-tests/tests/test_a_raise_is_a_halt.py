"""Plan row 7 (step 6), #7821: a raise is never a completion.

A raise had two representations in the floor: a halted face (an
``Incomplete`` whose effect is a ``RaiseEffect``, or a ``Halted`` arm), and a
``Complete`` whose value was a ``RaiseValue``.  The second came from one
producer, ``ground_exceptional_exit`` (``1 // 0``, ``1 < "a"``), and every
reader that asked only "is it one ``Complete``" and used the value could drop
the raise (#7799, #7820).

``ground_exceptional_exit`` now returns the halt, ``Incomplete(effect)``, and
``RaiseValue`` is gone.  The effect carries the exception value it raises
(``raised_value``), which is what an ``except`` clause tests and an ``as``
name binds.

Two real sources read differently since the change, and are pinned below
with their truthful halves:

- ``match 1 // 0:`` refused on main (``RaiseValue.to_term`` panicked: the
  raise was matched as the subject's value).  It is now the halt.
- ``def g(x=1 // 0)`` then ``g()`` completed on main: the raise was bound as
  the default's value and dropped.  The call now refuses by name ("default did
  not construct completely"), one of the refusal families listed on #7821.

The five shapes #7820's probe surfaced (#7821) are pinned as expected red.
None of them reaches the producer as a value: the call they make is a
``CallSiteValue`` that is never reduced (a lambda's ``py.call``, ``h(g)``
with ``g`` symbolic, ``Box()`` with no body), so the raise is never
evaluated at all.  That is a different defect from the two representations,
and this change does not reach it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import (
    WitnessPipelineError,
    run_source_through_real_solver,
)


def _tree(source: str):
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_source_tree.tree import SourceFile

    return SourceFile(
        (source, "test_witness.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )


def _function(source: str, name: str = "test_f"):
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome
    from sugar_source_tree import nodes

    (function,) = tuple(
        node
        for node in _tree(source).nodes()
        if isinstance(node, nodes.FunctionDef) and node.name == name
    )
    return function_universe_outcome(function)


def _faces(outcome) -> tuple[int, tuple[str, ...]]:
    """(completed faces, the exception name of each halted face)."""
    from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet, Halted

    if isinstance(outcome, Complete):
        assert outcome.follow().continues, outcome
        return 1, ()
    assert isinstance(outcome, ExitSet), outcome
    return (
        sum(isinstance(face, Completed) for face in outcome.exits),
        tuple(
            getattr(face.effect, "exception_name", type(face.effect).__name__)
            for face in outcome.exits
            if isinstance(face, Halted)
        ),
    )


# ---------------------------------------------------------------------------
# The producer.
# ---------------------------------------------------------------------------


def test_a_ground_exit_is_a_halt_carrying_the_exception_it_raises() -> None:
    from sugar_lift_py_tests.effect import RaiseEffect
    from sugar_lift_py_tests.floor import ExceptionValue
    from sugar_lift_py_tests.outcome import Incomplete
    from sugar_source_tree import nodes

    (division,) = tuple(
        node for node in _tree("a = 1 // 0\n").nodes() if isinstance(node, nodes.BinOp)
    )

    outcome = division.sugar().desugar(None)

    assert isinstance(outcome, Incomplete), outcome
    assert isinstance(outcome.effect, RaiseEffect)
    assert outcome.effect.exception_name == "ZeroDivisionError"
    assert isinstance(outcome.effect.raised_value, ExceptionValue)
    assert not outcome.follow().continues
    # No step runs after a raise.
    assert outcome.and_then(lambda value: pytest.fail("stepped")) is outcome


def test_the_floor_has_no_raise_value() -> None:
    import sugar_lift_py_tests.floor as floor

    assert not hasattr(floor, "RaiseValue")
    assert not hasattr(floor, "GuardedRaise")


# ---------------------------------------------------------------------------
# Twins at the reduction level.  One thing differs: the raising expression.
# ---------------------------------------------------------------------------

_MATCH = (
    "def test_f():\n    match {x}:\n        case 1:\n            a = 1\n    return 3\n"
)
_DEFAULT = "def g(x={x}):\n    return 1\n\n\ndef test_f():\n    a = g()\n    return 3\n"
_CLASS_FIELD_7799 = (
    "class Box:\n    limit = {x}\n\n    def __init__(self, n):\n"
    "        self.n = n\n\n\ndef test_f():\n    a = Box(1)\n    return 3\n"
)
_CALL_7820 = "def f():\n    return {x}\n\n\ndef test_f():\n    a = f()\n    return 3\n"

_FIXED = {
    "match-subject": _MATCH,
    "class-field-7799": _CLASS_FIELD_7799,
    "call-7820": _CALL_7820,
}
# The truthful subject of the match is 2, a value no case matches: ``match 1``
# with a matching ``case 1`` refuses on main and here alike
# (``'_ReducedBlock' object has no attribute 'contribution'``), which is not
# this change.
_TRUTHFUL = {"match-subject": "2", "class-field-7799": "3"}
_ALL_TRUTHFUL = {**_FIXED, "default-argument": _DEFAULT}


@pytest.mark.parametrize("shape", sorted(_ALL_TRUTHFUL))
def test_the_truthful_half_completes(shape: str) -> None:
    source = _ALL_TRUTHFUL[shape].format(x=_TRUTHFUL.get(shape, "1"))

    assert _faces(_function(source)) == (1, ())


@pytest.mark.parametrize("shape", sorted(_FIXED))
def test_the_lying_half_halts_with_the_raise(shape: str) -> None:
    assert _faces(_function(_FIXED[shape].format(x="1 // 0"))) == (
        0,
        ("ZeroDivisionError",),
    )


def test_a_raising_default_is_refused_by_name_not_bound_as_a_value() -> None:
    from sugar_source_tree.panic import SugarNotWritten

    with pytest.raises(SugarNotWritten, match="default did not construct completely"):
        _function(_DEFAULT.format(x="1 // 0"))


# ---------------------------------------------------------------------------
# The five shapes of #7821.  Expected red: the call is never reduced, so no
# raise reaches it, as a value or as a halt.
# ---------------------------------------------------------------------------

_FIVE = {
    "lambda-call": ("def test_f():\n    g = lambda: {x}\n    a = g()\n    return 3\n"),
    "raising-new": (
        "class Box:\n    def __new__(cls):\n        return {x}\n\n\n"
        "def test_f():\n    a = Box()\n    return 3\n"
    ),
    "function-passed-as-argument": (
        "def g():\n    return {x}\n\n\ndef h(f):\n    return f()\n\n\n"
        "def test_f():\n    a = h(g)\n    return 3\n"
    ),
    "raise-in-class-body": (
        "class Box:\n    if True:\n        {x}\n\n\n"
        "def test_f():\n    a = Box()\n    return 3\n"
    ),
    "raising-base": (
        "class Box({x}):\n    pass\n\n\ndef test_f():\n    a = Box()\n    return 3\n"
    ),
}
_FIVE_HALVES = {
    "lambda-call": ("1", "1 // 0"),
    "raising-new": ("1", "1 // 0"),
    "function-passed-as-argument": ("1", "1 // 0"),
    "raise-in-class-body": ("limit = 1", "raise ValueError"),
    "raising-base": ("object", "1 // 0"),
}
_NOT_REDUCED = (
    "the call is a CallSiteValue that is never reduced (a lambda's py.call, "
    "h(g) with g symbolic, Box() with no body): the raise is never evaluated, "
    "so it completes with no halted face (#7821; not the two representations)"
)


@pytest.mark.parametrize("shape", sorted(_FIVE))
def test_the_truthful_half_of_each_of_the_five_completes(shape: str) -> None:
    truthful, _lying = _FIVE_HALVES[shape]

    assert _faces(_function(_FIVE[shape].format(x=truthful))) == (1, ())


@pytest.mark.xfail(strict=True, reason=_NOT_REDUCED)
@pytest.mark.parametrize("shape", sorted(_FIVE))
def test_the_lying_half_of_each_of_the_five_halts(shape: str) -> None:
    _truthful, lying = _FIVE_HALVES[shape]

    completed, halts = _faces(_function(_FIVE[shape].format(x=lying)))

    assert completed == 0
    assert len(halts) == 1


# ---------------------------------------------------------------------------
# The same twins through the real solver.  A lying half that halts before the
# assert has no assertion row: halted arms of a reduction are not emitted
# (#7766), so the harness reports "no assertion rows", not ``unsat``.
# ---------------------------------------------------------------------------


def _solver_source(source: str) -> str:
    return source.replace("    return 3\n", "    assert 1 == 1\n")


# Through the solver the #7799 class has no ``__init__``: with one, its
# initializer universe is built over the halted class statement and mint
# refuses the file by name (pinned in test_class_body_assignment_routine.py).
_SOLVER = {
    **_FIXED,
    "class-field-7799": "class Box:\n    limit = {x}\n\n\ndef test_f():\n    Box()\n    return 3\n",
}
_ALL_SOLVER_TRUTHFUL = {**_SOLVER, "default-argument": _DEFAULT}


@pytest.mark.parametrize("shape", sorted(_ALL_SOLVER_TRUTHFUL))
def test_the_truthful_half_is_sat(shape: str, tmp_path: Path) -> None:
    source = _ALL_SOLVER_TRUTHFUL[shape].format(x=_TRUTHFUL.get(shape, "1"))

    truthful = run_source_through_real_solver(tmp_path / "t", _solver_source(source))

    assert truthful.verdict == "sat"


@pytest.mark.parametrize("shape", sorted(_SOLVER))
def test_the_lying_half_has_no_assertion_row(shape: str, tmp_path: Path) -> None:
    lying = run_source_through_real_solver(
        tmp_path / "l", _solver_source(_SOLVER[shape].format(x="1 // 0"))
    )

    with pytest.raises(WitnessPipelineError, match="no assertion rows"):
        lying.verdict


def test_a_raising_default_is_not_sat(tmp_path: Path) -> None:
    with pytest.raises(WitnessPipelineError):
        run_source_through_real_solver(
            tmp_path / "l", _solver_source(_DEFAULT.format(x="1 // 0"))
        ).verdict


@pytest.mark.parametrize("shape", sorted(_FIVE))
def test_the_truthful_half_of_each_of_the_five_is_sat(
    shape: str, tmp_path: Path
) -> None:
    truthful, _lying = _FIVE_HALVES[shape]

    result = run_source_through_real_solver(
        tmp_path / "t", _solver_source(_FIVE[shape].format(x=truthful))
    )

    assert result.verdict == "sat"


@pytest.mark.xfail(strict=True, reason=_NOT_REDUCED)
@pytest.mark.parametrize("shape", sorted(_FIVE))
def test_the_lying_half_of_each_of_the_five_is_not_sat(
    shape: str, tmp_path: Path
) -> None:
    _truthful, lying = _FIVE_HALVES[shape]

    result = run_source_through_real_solver(
        tmp_path / "l", _solver_source(_FIVE[shape].format(x=lying))
    )

    try:
        verdict = result.verdict
    except WitnessPipelineError as exc:
        # The halt before the assert: no row, as for the fixed shapes.
        assert "no assertion rows" in str(exc)
        return
    assert verdict != "sat"
