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
    assert lying.verdict == "unsat"
