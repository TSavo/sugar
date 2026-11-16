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

The five shapes #7820's probe surfaced (#7821) are pinned beside them.
None of them reached the producer as a value: the call they make was a
``CallSiteValue`` that was never reduced (a lambda's ``py.call``, ``h(g)``
with ``g`` symbolic, ``Box()`` with no body), so the raise was never
evaluated at all.  That is a different defect from the two representations.
The lambda call, the returned ``__new__``, the raising base and ``h(g)`` are
reduced since: at the reduction level their lying halves halt, and are pinned
green; the other is expected red there.  ``h(g)`` hands ``h`` the function
``g``'s ``def`` statement built (a function-body read of an undecorated
module ``def``'s name is that function, #7757), and ``f()`` inside ``h``
applies it through the one call door.  Through the solver no lying half of
the five is ``sat``: a call that is not reduced is the unanswered call, which
owes its member.

Since #7757 steps 5 and 6 (the owner's ruling of 2026-11-15, "Edge, join at
prove"; #8705, #8738) a call of a same-file function or class is its
coordinate and an edge to the callee's join symbol: the reduction never
follows the callee's body.  At the reduction such a call is the edge's two
faces -- it completes under its atom, and the undetermined raise (no
exception name) under the complement -- whatever the callee does; what the
callee raises is its contract's panic loci, joined at prove.  The shapes
whose raise sits in a callee read that way below (``_CALL_EDGE``).  A raise
the reduction itself reaches (the ``match`` subject, a class statement that
halts in the module's run) still halts there.  Since #8751 no path
binds a body to a call, so a lambda bound to a local name and called is an
edge too.
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

# A same-file call at the reduction (#7757 steps 5 and 6): the edge's two
# faces, one completion and the undetermined raise, which names no exception
# (``UnknownCalleeCallV1.faces``).  What the callee raises is decided at prove
# from its contract's panic loci, never here.
_CALL_EDGE = (1, (None,))
# ``a = g()``, ``a = f()``, ``a = Box(1)``: the truthful half's call is an
# edge.  The lying ``class-field-7799`` half is not: its class statement
# halts in the module's run, so its read of ``Box`` is that halt.
_TRUTHFUL_CALL_EDGE = {"call-7820", "class-field-7799", "default-argument"}
_LYING_CALL_EDGE = {"call-7820"}


@pytest.mark.parametrize("shape", sorted(_ALL_TRUTHFUL))
def test_the_truthful_half_completes(shape: str) -> None:
    source = _ALL_TRUTHFUL[shape].format(x=_TRUTHFUL.get(shape, "1"))

    expected = _CALL_EDGE if shape in _TRUTHFUL_CALL_EDGE else (1, ())
    assert _faces(_function(source)) == expected


@pytest.mark.parametrize("shape", sorted(_FIXED))
def test_the_lying_half_halts_with_the_raise(shape: str) -> None:
    # ``f()`` over ``def f(): return 1 // 0`` is the edge's two faces: the
    # ``ZeroDivisionError`` is ``f``'s contract's panic locus, joined at prove.
    expected = (
        _CALL_EDGE if shape in _LYING_CALL_EDGE else (0, ("ZeroDivisionError",))
    )
    assert _faces(_function(_FIXED[shape].format(x="1 // 0"))) == expected


def test_a_raising_default_is_refused_by_name_not_bound_as_a_value() -> None:
    # Python halts the module at ``def g(x=1 // 0)``: no evaluation of the
    # ``def`` ever reaches ``g()``.  The call states exactly that and refuses
    # by name; the raise is never bound as the default's value.
    from sugar_source_tree.panic import SugarNotWritten

    with pytest.raises(SugarNotWritten, match="default not bound where the call runs"):
        _function(_DEFAULT.format(x="1 // 0"))


# ---------------------------------------------------------------------------
# The five shapes of #7821.  Each was red: the call was never reduced, so no
# raise reached it, as a value or as a halt.  All five are reduced now.
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


# Every truthful half is what Python decides: one completion.  ``h(g)`` hands
# ``h`` an undecorated ``def`` as a value, and ``f()`` inside ``h`` calls it.
# The read of ``g`` in ``test_f`` is the function its ``def`` statement built
# (``SourceUnit.function_definition_for_read``: the definition's own frame,
# as a lambda is a ``LambdaCallable`` and a decorated ``def``'s name is bound
# to one), so ``f()`` applies it through the one call door, as ``g()`` does.
# It was pinned undecided (one completion beside an undetermined raise) while
# the read was the bare name with no function value behind it (#7757).
#
# Since #7757 steps 5 and 6, ``Box()`` and ``h(g)`` are calls of a same-file
# class and function: the edge's two faces at the reduction, whatever the
# class, ``h`` or the lambda runs (``_FIVE_CALL_EDGE``): since #8751 no
# path binds a body to a call, a lambda bound to a local name included.
_FIVE_CALL_EDGE = {
    "function-passed-as-argument",
    "lambda-call",
    "raise-in-class-body",
    "raising-base",
    "raising-new",
}


@pytest.mark.parametrize("shape", sorted(_FIVE))
def test_the_truthful_half_of_each_of_the_five_completes(shape: str) -> None:
    truthful, _lying = _FIVE_HALVES[shape]

    expected = _CALL_EDGE if shape in _FIVE_CALL_EDGE else (1, ())
    assert _faces(_function(_FIVE[shape].format(x=truthful))) == expected


# A lambda bound to a local name and called (``g = lambda: 1 // 0; g()``) is
# reduced now: the call runs the lambda's body, which raises, so the call
# halts with no completion, as Python does.  So is ``Box()`` over a class
# whose own ``def __new__`` returns ``1 // 0`` and whose ``__init__`` is
# ``object``'s (``ClassDef.returned_new``): the class call runs that
# ``__new__`` through the one method door, and its halt is the call's.  So is
# ``Box()`` over ``class Box(1 // 0)``: the class statement halts at its base
# and no class is built, so the lying half has no completion and one halt.
# The expected-red mark on it was XPASS(strict) on the main scorecard at
# 18a14aa25 (#8416), so the mark is gone and the assertion stands.  So is
# ``h(g)`` over ``def g(): return 1 // 0``: ``f()`` inside ``h`` applies the
# function ``g`` names, whose body raises, so the call halts with no
# completion (#7757).  So is ``Box()`` over ``class Box: if True: raise
# ValueError``: the class body is a block that admits every simple statement
# the block reducer reduces (``ClassDef._require_class_members``), so the
# ``raise`` halts the class statement in the module's run, no import
# completes, and the read of ``Box`` is that run's one halt
# (``tree_enumerate.module_run_halts``).  It was refused by name as an
# unsupported conditional class member, which the strict expected-red mark
# held; the mark is gone and the assertion stands.
#
# Since #7757 steps 5 and 6 (and #8751, which deleted the last application
# of a callee body at lift) the lying ``Box()`` over a raising ``__new__``,
# ``h(g)`` and ``g()`` over ``g = lambda: 1 // 0`` are edges: the edge's two
# faces at the reduction, the raise being the callee's contract's panic
# locus, joined at prove (``_FIVE_LYING_CALL_EDGE``).  The raising base and
# the raise in the class body halt the class statement in the module's run,
# so the read of ``Box`` is that halt, as before.
_FIVE_LYING_CALL_EDGE = {"function-passed-as-argument", "lambda-call", "raising-new"}


@pytest.mark.parametrize("shape", sorted(_FIVE))
def test_the_lying_half_of_each_of_the_five_halts(shape: str) -> None:
    _truthful, lying = _FIVE_HALVES[shape]

    faces = _faces(_function(_FIVE[shape].format(x=lying)))

    if shape in _FIVE_LYING_CALL_EDGE:
        assert faces == _CALL_EDGE
        return
    completed, halts = faces
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


# A same-file call's completion is stated over its call term, read or
# discarded, and prove joins the callee's halts under it (#8753): the
# truthful ``f()``/``g()``/``Box()`` completes, the lying ``f()`` certainly
# halts, decided at prove rather than at the reduction.
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
    "raising-new": (
        "Box's own contract dispatches its source __new__ as a static method "
        "on the class (step 6, #7757 A4), so what it returned is not seen at "
        "the lift, and type.__call__'s type(obj).__init__ is the dispatched "
        "call on that result with no class stated for it: prove resolves no "
        "__init__ without the receiver's class, so the call is owed. It "
        "shares the __new__ edge's site, and prove's join keys answers by the "
        "site and the target symbol the call names, so it reads its own owed "
        "member, never __new__'s contract. Decided at step 9 once a "
        "type.__call__ law relates __new__'s returned value to the class "
        "__init__ is dispatched over"
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

    # ``Box()`` is an edge: its completion, stated over its call term, is
    # joined to the class's contract at prove (#8753).
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
