"""Twins: ``del o.f`` that runs code exposes what the receiver holds, as a
call on it does (#7757 H4).

``del o.f`` is ``type(o).__delattr__(o, "f")``.  Where that is not
``object``'s, the delete is the dispatched call (``ObjectValue.
_dispatched_delattr``), and the code it runs may change anything the
receiver reaches.  The delete exposed only names bound to the receiver
itself, and ``_may_change`` answered False for any source instance, so a
name holding an object the receiver holds kept its old value across the
call: for

    def drop(self, name):
        self.items.append(2)

    class Box:
        def __init__(self):
            self.items = [1]
            self.y = 0
            c = self.items
            del self.y
            self.n = len(c)

    Box.__delattr__ = drop

``Box().n`` read ``1``; Python gives ``2``.  The delete is now exposed as a
method call on its receiver is (``container_mutation._call_targets``): a
name sharing what the receiver holds reads its value after the call, which
the receiver's value decides may have changed.

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
    # The ``__delattr__`` the module stores on the class appends to the list
    # the receiver holds; ``c`` holds that list.
    "delattr-changes-a-held-list": (
        "def drop(self, name):\n"
        "    self.items.append(2)\n"
        "\n"
        "\n"
        "class Box:\n"
        "    def __init__(self):\n"
        "        self.items = [1]\n"
        "        self.y = 0\n"
        "        c = self.items\n"
        "        del self.y\n"
        "        self.n = len(c)\n"
        "\n"
        "\n"
        "Box.__delattr__ = drop\n"
        "\n"
        "\n"
        "def test_box():\n"
        "    assert {claim}\n",
        "Box().n == 2",
        # The value a delete that exposed nothing the receiver holds leaves.
        "Box().n == 1",
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
def test_a_delete_that_runs_code_never_refutes_a_truth_nor_admits_a_lie(
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
