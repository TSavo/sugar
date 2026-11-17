"""Twins: a class body that leaves on several faces builds the class on each
(#7757, step 6).

Two refusals of ``ClassDefinitionSugar.desugar`` refused a whole class where
its body reduced on more than one face:

- "class field ... did not construct completely": a body with several
  completed faces (a field whose right-hand side has several completed
  values; ``numpy/f2py/tests/test_character.py`` and
  ``test_crackfortran.py`` build a field in a class-body loop).  The class
  statement now builds one class on each completed face, under that face's
  guard, as a base with several completions builds one class per
  completion.
- "class conditional guard is not a ground bool literal": an ``if`` of the
  body whose test the truth rule does not decide (``numpy/lib/_iotools.py``'s
  ``StringConverter``, ``pandas/io/formats/style.py``'s ``MyStyler``).  The
  ``if`` reduces both arms under its test's guard (``IfSugar``), and the
  class is built once per arm, under that arm's guard, holding that arm's
  rows only.

A lying claim is never ``sat``; a truthful one is never ``unsat``.  Each
half goes through ``run_source_through_real_solver``: real ``sugar mint``
then real ``sugar prove``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import (
    claim_verdict,
    prove_verdict,
    run_source_through_real_solver,
)

# A field with two completed values (``flag`` truthy, else ``int(flag)``):
# the class is built on each, and ``limit`` is 3 on both.
_SEVERAL_VALUES = (
    "def make(flag):\n"
    "    class Box:\n"
    "        size = flag or int(flag)\n"
    "        limit = 3\n"
    "    return Box.limit\n"
    "\n"
    "\n"
    "def test_box():\n"
    "    assert {claim}\n"
)

# An undecided ``if``: each class holds the ``limit`` of its own arm.
_UNDECIDED_IF = (
    "def make(flag):\n"
    "    class Box:\n"
    "        if flag:\n"
    "            limit = 1\n"
    "        else:\n"
    "            limit = 2\n"
    "    return Box.limit\n"
    "\n"
    "\n"
    "def test_box():\n"
    "    assert {claim}\n"
)

# An undecided ``if`` whose arm changes a list an earlier field holds
# (``_iotools.StringConverter._mapper``): ``limit``, after it, is 3 on both.
_UNDECIDED_IF_CHANGES_A_FIELD = (
    "def make(flag):\n"
    "    class Box:\n"
    "        items = [1]\n"
    "        if flag:\n"
    "            items.append(2)\n"
    "        limit = 3\n"
    "    return Box.limit\n"
    "\n"
    "\n"
    "def test_box():\n"
    "    assert {claim}\n"
)

# ``name: (source, claim, half)``.
_CASES = {
    "several-values-truthful": (_SEVERAL_VALUES, "make(0) == 3", "truthful"),
    "several-values-lying": (_SEVERAL_VALUES, "make(0) == 4", "lying"),
    "undecided-if-truthful": (_UNDECIDED_IF, "make(1) == 1", "truthful"),
    "undecided-if-lying": (_UNDECIDED_IF, "make(1) == 2", "lying"),
    "undecided-if-changes-a-field-truthful": (
        _UNDECIDED_IF_CHANGES_A_FIELD,
        "make(0) == 3",
        "truthful",
    ),
    "undecided-if-changes-a-field-lying": (
        _UNDECIDED_IF_CHANGES_A_FIELD,
        "make(0) == 4",
        "lying",
    ),
}


def _claims_line(source: str) -> int:
    """The line of the test function's ``def``: it follows ``make``."""
    for number, line in enumerate(source.splitlines(), start=1):
        if line.startswith("def test_"):
            return number
    raise AssertionError("the source states no test function")


@pytest.mark.parametrize("case", sorted(_CASES))
def test_a_class_built_on_each_face_never_refutes_a_truth_nor_admits_a_lie(
    tmp_path: Path, case: str
) -> None:
    source, claim, half = _CASES[case]
    text = source.format(claim=claim)
    result = run_source_through_real_solver(tmp_path / case, text)
    verdict = claim_verdict(result.prove_doc, claims_from_line=_claims_line(text))
    whole = prove_verdict(result.prove_doc)
    if half == "lying":
        assert verdict != "sat", result.prove_doc
        assert whole != "sat", result.prove_doc
    else:
        assert verdict != "unsat", result.prove_doc
        assert whole != "unsat", result.prove_doc
