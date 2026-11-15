"""Solver twins: a cited ``with`` keeps its suppressed face (step 6).

Truthful: ``open`` comes from ``tarfile``, which the lifter does not have, so
the manager is cited and whether its ``__exit__`` suppresses the body's
``ZeroDivisionError`` is undecided.  ``g`` may therefore return 7, and the
claim ``g("x") == 7`` is not refuted.  It is not proven either: no proof for
``tarfile.open`` is staged in ``.sugar/imports/``, so the call is an edge
nothing answers, the proof owes it as an ``undecided`` member (step 8), and a
source that owes anything is never ``sat``.  The truthful half reads ``open``:
this twin states "not bridged", and it reads ``sat`` on the day a proof that
answers ``tarfile.open`` is staged.

Lying: the one thing changed is that ``open`` is bound to source the lifter
HAS, a manager whose ``__exit__`` returns False.  The body's raise always
propagates, ``g`` never returns, and the claim is refuted: ``unsat``.

Before the cited ``with`` kept its suppressed face, the body's raise was the
truthful half's only face and it read ``unsat`` like the lying one.  ``open``
against ``unsat`` is what the kept face shows.
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.witness_harness import run_source_through_real_solver

_TAIL = (
    "\n"
    "def g(p):\n"
    "    with open(p):\n"
    "        1 / 0\n"
    "    return 7\n"
    "\n"
    "\n"
    "def test_claim():\n"
    "    assert g('x') == 7\n"
)


def test_cited_with_keeps_its_suppressed_face_through_the_solver(
    tmp_path: Path,
) -> None:
    truthful = run_source_through_real_solver(
        tmp_path / "t", "from tarfile import open\n" + _TAIL
    )
    lying = run_source_through_real_solver(
        tmp_path / "l",
        "class open:\n"
        "    def __init__(self, p):\n"
        "        self.p = p\n"
        "    def __enter__(self):\n"
        "        return self\n"
        "    def __exit__(self, *exc):\n"
        "        return False\n" + _TAIL,
    )
    # Not bridged: ``tarfile.open`` is owed, so the claim is neither proven
    # nor refuted.
    assert truthful.verdict == "open"
    assert truthful.prove_doc["owed"] >= 1
    # Lying: ``open(p)`` is a call of a same-file class, its coordinate and
    # edge (#7757 step 6, #8738), and the manager the ``with`` enters is that
    # call's result.  The class's contract states the fields its
    # construction set (``attr:p(python:after(out, "out")) == p``, #8746),
    # never the instance's class.  ``__enter__``/``__exit__`` on the result
    # are the unanswered call, so whether ``__exit__`` suppresses the body's
    # raise is undecided and the claim is not refuted: ``open`` on main
    # (scorecard 43738710481), listed on #7661.  Never ``sat`` for the lie.
    #
    # Step 8 (#8750, #8778, #8799) does not reach it, for two named reasons,
    # neither of them step 7 part 1 (what a callee leaves in what it was
    # handed):
    # 1. Dispatch on a class call's result is supplied only for a class whose
    #    construction runs no source code (``_bare_instance_symbol``:
    #    ``object.__new__`` and ``object.__init__``), because the receiver
    #    class value ``python:instance(<class>, <field>...)`` names every
    #    field the instance's ``__dict__`` may hold and prove's
    #    ``dispatched_symbol`` reads those fields before the class.  ``open``
    #    runs a source ``__init__``: its fields are its contract's, which
    #    neither ``receiver_dispatch.class_value`` nor dispatch reads.  (An
    #    implicit special-method call reads ``type(m).__exit__``, where no
    #    field can shadow, but dispatch states no such lookup.)
    # 2. ``__exit__(self, *exc)``: prove's one binder
    #    (``consistency::call_argument_formals``) binds no ``*args``
    #    parameter, so ``__exit__(m, type, value, tb)`` would not fit the
    #    contract even when dispatched, and stays owed.
    assert lying.verdict == "open"
