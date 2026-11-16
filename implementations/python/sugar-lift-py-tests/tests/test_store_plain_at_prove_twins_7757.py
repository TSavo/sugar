"""Twins: a field store on a source instance is the plain store only where
prove decides it (#7757 H1b).

``o.f = v`` is ``type(o).__setattr__(o, "f", v)``.  The lift decided at
reduce, by its own walk of the class (``ObjectValue.field_store_route``),
that the store is the plain ``__dict__`` store, a source ``__setattr__``'s
or a descriptor's call, or a property's certain ``AttributeError``.  That
walk never asked ``__slots__``: for

    class P:
        __slots__ = ('x',)
        def __init__(self):
            self.x = 1
            self.y = 2

it took ``self.y = 2`` as the plain store, so the constructor completed and
``P()`` raising ``AttributeError`` -- what Python does -- was refuted.  The
store now has two faces: the plain store under ``python:plain_store(<class>,
"f")``, which prove alone decides (``consistency::plain_store_holds``,
``__slots__`` among its hooks), and the dispatched ``__setattr__`` call under
its complement, its halt kept.

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

# ``name: (source, truthful claim, lying claim)``: ``source`` is a
# ``str.format`` template.
_SHAPES = {
    # A store outside ``__slots__`` raises ``AttributeError``.
    "store-outside-slots-raises": (
        "class P:\n"
        "    __slots__ = ('x',)\n"
        "\n"
        "    def __init__(self):\n"
        "        self.x = 1\n"
        "        self.y = 2\n"
        "\n"
        "\n"
        "def test_p():\n"
        "    try:\n"
        "        P()\n"
        "        raised = False\n"
        "    except AttributeError:\n"
        "        raised = True\n"
        "    assert {claim}\n",
        "raised",
        # The face a store that dropped its raise would leave.
        "not raised",
    ),
    # A property with no setter: Python's store raises ``AttributeError``,
    # which the handler catches.
    "property-store-caught": (
        "class Box:\n"
        "    def __init__(self):\n"
        "        self.x = 1\n"
        "        try:\n"
        "            self.p = 5\n"
        "        except AttributeError:\n"
        "            self.x = 2\n"
        "\n"
        "    @property\n"
        "    def p(self):\n"
        "        return 0\n"
        "\n"
        "\n"
        "def test_box():\n"
        "    assert {claim}\n",
        "Box().x == 2",
        "Box().x == 1",
    ),
}


def _claims_line(source: str) -> int:
    """The line of the test function's ``def``: it follows the class."""
    for number, line in enumerate(source.splitlines(), start=1):
        if line.startswith("def test_"):
            return number
    raise AssertionError("the source states no test function")


@pytest.mark.parametrize("half", ["truthful", "lying"])
@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_a_store_decided_at_prove_never_refutes_a_truth_nor_admits_a_lie(
    tmp_path: Path, shape: str, half: str
) -> None:
    source, truthful, lying = _SHAPES[shape]
    text = source.format(claim=truthful if half == "truthful" else lying)
    result = run_source_through_real_solver(tmp_path / shape / half, text)
    verdict = claim_verdict(result.prove_doc, claims_from_line=_claims_line(text))
    whole = prove_verdict(result.prove_doc)
    if half == "lying":
        assert verdict != "sat", result.prove_doc
        assert whole != "sat", result.prove_doc
    else:
        assert verdict != "unsat", result.prove_doc
        assert whole != "unsat", result.prove_doc
