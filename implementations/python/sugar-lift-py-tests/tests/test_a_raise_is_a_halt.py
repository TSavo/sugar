"""Plan row 7 (step 6), #7821: a raise is never a completion.

A raise had two representations in the floor: a halted face (a ``Halted``
arm whose effect is a ``RaiseEffect``), and a completed value that was a
``RaiseValue``.  The second came from one producer,
``ground_exceptional_exit`` (``1 // 0``, ``1 < "a"``), and every reader that
asked only "is it one completed value" and used the value could drop the raise
(#7799, #7820).

``ground_exceptional_exit`` now returns the halt, ``ExitSet.halted(effect)``, and
``RaiseValue`` is gone.  The effect carries the exception value it raises
(``raised_value``), which is what an ``except`` clause tests and an ``as``
name binds.

Two real sources read differently since the change, and are pinned below
with their truthful halves:

- ``match 1 // 0:`` refused on main (``RaiseValue.to_term`` panicked: the
  raise was matched as the subject's value).  It is now the halt.
- ``def g(x=1 // 0)`` then ``g()`` completed on main: the raise was bound as
  the default's value and dropped.  The call now refuses by name ("default not
  bound where the call runs": no evaluation of the ``def`` reached it), one of
  the refusal families listed on #7821; through the solver the refused
  function is owed and the file reads ``open``.

The five shapes #7820's probe surfaced (#7821) are pinned as expected red.
None of them reaches the producer as a value: the call they make is a
``CallSiteValue`` that is never reduced (a lambda's ``py.call``, ``h(g)``
with ``g`` symbolic, ``Box()`` with no body), so the raise is never
evaluated at all.  That is a different defect from the two representations,
and this change does not reach it.  The lambda call is reduced since: at the
reduction level its lying half halts, and is pinned green.
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
    from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted

    assert isinstance(outcome, ExitSet), outcome
    value = outcome.completed_value()
    if value is not None:
        assert value.follow_rest().continues, outcome
        return 1, ()
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
    from sugar_source_tree import nodes

    (division,) = tuple(
        node for node in _tree("a = 1 // 0\n").nodes() if isinstance(node, nodes.BinOp)
    )

    outcome = division.sugar().desugar(None)

    # One arm, and it halts: nothing completes, so nothing continues.
    assert len(outcome.exits) == 1 and outcome.halts() == outcome.exits, outcome
    (halt,) = outcome.halts()
    assert isinstance(halt.effect, RaiseEffect)
    assert halt.effect.exception_name == "ZeroDivisionError"
    assert isinstance(halt.effect.raised_value, ExceptionValue)
    assert outcome.completed_value() is None
    # No step runs after a raise.
    assert outcome.and_then(lambda value: pytest.fail("stepped")) == outcome


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
    # Python halts the module at ``def g(x=1 // 0)``: no evaluation of the
    # ``def`` ever reaches ``g()``.  The call states exactly that and refuses
    # by name; the raise is never bound as the default's value.
    from sugar_source_tree.panic import SugarNotWritten

    with pytest.raises(SugarNotWritten, match="default not bound where the call runs"):
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


# A truthful half Python decides and the reduction does not: ``h(g)`` hands
# ``h`` a ``def`` as a value, and ``f()`` inside ``h`` calls it.  The floor
# applies a lambda reached as a value (``LambdaCallable``), a class and a
# bound method; a ``def`` reached as a value has no value that applies it, so
# ``f()`` is the unanswered call in ``test_f``'s frame too: one completion
# under the call's own guard beside its undetermined raise, which names no
# exception.  It is not a completion alone, and it is pinned as what it is.
_FIVE_UNDECIDED = {"function-passed-as-argument"}


@pytest.mark.parametrize("shape", sorted(set(_FIVE) - _FIVE_UNDECIDED))
def test_the_truthful_half_of_each_of_the_five_completes(shape: str) -> None:
    truthful, _lying = _FIVE_HALVES[shape]

    assert _faces(_function(_FIVE[shape].format(x=truthful))) == (1, ())


@pytest.mark.parametrize("shape", sorted(_FIVE_UNDECIDED))
def test_a_truthful_half_calling_a_def_passed_as_a_value_is_not_decided(
    shape: str,
) -> None:
    truthful, _lying = _FIVE_HALVES[shape]

    assert _faces(_function(_FIVE[shape].format(x=truthful))) == (1, (None,))


# A lambda bound to a local name and called (``g = lambda: 1 // 0; g()``) is
# reduced now: the call runs the lambda's body, which raises, so the call
# halts with no completion, as Python does.  So is ``Box()`` over a class
# whose own ``def __new__`` returns ``1 // 0`` and whose ``__init__`` is
# ``object``'s (``ClassDef.returned_new``): the class call runs that
# ``__new__`` through the one method door, and its halt is the call's.
_FIVE_REDUCED = {"lambda-call", "raising-new"}


@pytest.mark.parametrize(
    "shape",
    [
        shape
        if shape in _FIVE_REDUCED
        else pytest.param(
            shape, marks=pytest.mark.xfail(strict=True, reason=_NOT_REDUCED)
        )
        for shape in sorted(_FIVE)
    ],
)
def test_the_lying_half_of_each_of_the_five_halts(shape: str) -> None:
    _truthful, lying = _FIVE_HALVES[shape]

    completed, halts = _faces(_function(_FIVE[shape].format(x=lying)))

    assert completed == 0
    assert len(halts) == 1


# ---------------------------------------------------------------------------
# The same twins through the real solver.  A lying half halts before the
# assert on its every arm: no arm of the test function completes, so the
# assert no arm reached states the halted arms' guards negated, and a halt
# under truth reads ``unsat`` (#7766): the test certainly raises, so it fails.
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
def test_the_lying_half_is_unsat(shape: str, tmp_path: Path) -> None:
    lying = run_source_through_real_solver(
        tmp_path / "l", _solver_source(_SOLVER[shape].format(x="1 // 0"))
    )

    assert lying.verdict == "unsat"


def test_a_raising_default_is_not_sat(tmp_path: Path) -> None:
    # The refused ``test_f`` is its refused member (step 8): its claim is
    # owed, so the file reads ``open``, never ``sat`` and never a pipeline
    # error (``witness_harness._is_assertion_row``).
    result = run_source_through_real_solver(
        tmp_path / "l", _solver_source(_DEFAULT.format(x="1 // 0"))
    )
    assert result.verdict == "open"
    assert result.prove_doc["owed"] >= 1


# A truthful half Python decides whose file no proof can: one of its
# functions, proved on its own (step 8), owes a call nothing in that proof
# answers, so the file reads ``open``, stated, and never ``sat``, however
# the test function's own claim is decided.
_FIVE_OPEN = {
    "function-passed-as-argument": (
        "h's own proof calls its formal: f() is a call of an arrived value, "
        "which no actual binds where h is proved on its own, so it is the "
        "unanswered call and h owes its member; only a caller's frame "
        "(test_f's h(g)) binds f"
    ),
}


@pytest.mark.parametrize("shape", sorted(set(_FIVE) - set(_FIVE_OPEN)))
def test_the_truthful_half_of_each_of_the_five_is_sat(
    shape: str, tmp_path: Path
) -> None:
    truthful, _lying = _FIVE_HALVES[shape]

    result = run_source_through_real_solver(
        tmp_path / "t", _solver_source(_FIVE[shape].format(x=truthful))
    )

    assert result.verdict == "sat"


@pytest.mark.parametrize("shape", sorted(_FIVE_OPEN))
def test_a_truthful_half_whose_helper_owes_a_call_is_open(
    shape: str, tmp_path: Path
) -> None:
    truthful, _lying = _FIVE_HALVES[shape]

    result = run_source_through_real_solver(
        tmp_path / "t", _solver_source(_FIVE[shape].format(x=truthful))
    )

    assert result.verdict == "open", _FIVE_OPEN[shape]
    assert result.prove_doc["owed"] >= 1, _FIVE_OPEN[shape]


# A lying half is never ``sat``, reduced or not.  Where the call is reduced
# its raise is the test function's only arm and the assert no arm reached is
# refuted.  Where it is not (``_NOT_REDUCED``), the call is the unanswered
# call: it owes its ``undecided`` member (step 8), and a source that owes
# anything is never ``sat``.  This was marked expected-red while a call that
# was never reduced completed alone; it no longer does, so the mark is gone.
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
        # No assertion row at all: nothing about the claim was stated.
        assert "no assertion rows" in str(exc)
        return
    assert verdict != "sat"
