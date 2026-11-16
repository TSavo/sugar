"""Twins: ``==`` Python answers by identity is the one identity rule, never
a free ``py.eq`` (#7757, step 6).

``==`` is ``type(a).__eq__(a, b)``, then the reflection.  ``object.__eq__``
and ``type.__eq__`` answer ``True`` for one object and ``NotImplemented``
otherwise; a singleton's ``__eq__`` answers ``NotImplemented`` for another
type.  Where both sides answer so, Python falls back to ``a is b``.

Before, two instances of a class whose MRO binds no ``__eq__`` fell to
``resolve_equality_atom``'s ``py.eq(py.object.identity(..),
py.object.identity(..))``, and two classes to ``py.eq(python:type(A),
python:type(B))``, left bare because a class testifies to no value
(the compare post-pass, since deleted).  ``py.eq`` over terms nothing
interprets is a predicate the solver chooses, so the lie ``a == b`` over two
objects Python made apart could read ``sat``.  Now
``object_identity.equality_by_identity`` answers them by the identity rule
(``object_identity`` for instances, ``term_identity`` for classes of
metaclass ``type``), and any other equality over a class is the floor's
one undecided equality (``equality_atom.answered_equality``), which owes.

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

_PLAIN = "class P:\n    pass\n\n\n"
_CLASSES = "class A:\n    pass\n\n\nclass B:\n    pass\n\n\n"

# ``name: (source, truthful claim, lying claim)``.
_SHAPES = {
    "two-instances": (
        _PLAIN + "def test_eq():\n"
        "    a = P()\n"
        "    b = P()\n"
        "    assert {claim}\n",
        "a != b",
        "a == b",
    ),
    "one-instance-twice": (
        _PLAIN + "def test_eq():\n"
        "    a = P()\n"
        "    b = a\n"
        "    assert {claim}\n",
        "a == b",
        "a != b",
    ),
    "instance-and-none": (
        _PLAIN + "def test_eq():\n"
        "    a = P()\n"
        "    assert {claim}\n",
        "a != None",
        "a == None",
    ),
    "two-classes": (
        _CLASSES + "def test_eq():\n    assert {claim}\n",
        "A != B",
        "A == B",
    ),
    "one-class": (
        _CLASSES + "def test_eq():\n    assert {claim}\n",
        "A == A",
        "A != A",
    ),
    "local-classes": (
        "def test_eq():\n"
        "    class A:\n"
        "        pass\n"
        "\n"
        "    class B:\n"
        "        pass\n"
        "\n"
        "    assert {claim}\n",
        "A != B",
        "A == B",
    ),
}


def _claims_line(source: str) -> int:
    """The line of the test function's ``def``: it follows every helper."""
    for number, line in enumerate(source.splitlines(), start=1):
        if line.startswith("def test_"):
            return number
    raise AssertionError("the source states no test function")


@pytest.mark.parametrize("half", ["truthful", "lying"])
@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_equality_by_identity_is_never_a_free_choice(
    tmp_path: Path, shape: str, half: str
) -> None:
    source, truthful, lying = _SHAPES[shape]
    claim = truthful if half == "truthful" else lying
    text = source.format(claim=claim)
    result = run_source_through_real_solver(tmp_path / shape / half, text)
    verdict = claim_verdict(result.prove_doc, claims_from_line=_claims_line(text))
    whole = prove_verdict(result.prove_doc)
    if half == "lying":
        assert verdict != "sat", result.prove_doc
        assert whole != "sat", result.prove_doc
    else:
        assert verdict != "unsat", result.prove_doc
        assert whole != "unsat", result.prove_doc
