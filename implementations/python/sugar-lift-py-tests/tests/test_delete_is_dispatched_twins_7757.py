"""Twins: every ``del o.f`` on a source instance is the dispatched
``__delattr__`` (#7757 H1c).

``ObjectValue.delattr`` decided at lift, by its own walk of the class
namespace, that a delete under ``object``'s ``__delattr__`` removes a held
field, that a property's delete raises ``AttributeError``, and that an
instance whose contents are not current is the undecided delete: a second
answer to the question prove's one walk of the order answers for a
formal's delete (``consistency::dispatch_walk``).  The delete is now that
dispatched call for every name; only ``del o.__class__`` under ``object``'s
``__delattr__`` keeps its certain ``TypeError`` (builtin semantics, not the
walk).

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
    # A held field under ``object``'s ``__delattr__``: Python removes it and
    # leaves ``x``.
    "held-field-delete": (
        "class Box:\n"
        "    def __init__(self):\n"
        "        self.x = 1\n"
        "        self.y = 2\n"
        "        del self.y\n"
        "\n"
        "\n"
        "def test_box():\n"
        "    assert {claim}\n",
        "Box().x == 1",
        "Box().x == 2",
    ),
    # A property with no deleter: Python raises ``AttributeError``, which the
    # handler catches.
    "property-delete-caught": (
        "class Box:\n"
        "    def __init__(self):\n"
        "        self.x = 1\n"
        "        try:\n"
        "            del self.p\n"
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
        # The face a delete that dropped its raise would leave.
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
def test_a_dispatched_delete_never_refutes_a_truth_nor_admits_a_lie(
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
