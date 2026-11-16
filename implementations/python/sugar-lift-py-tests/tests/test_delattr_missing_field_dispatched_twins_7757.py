"""Twins: ``del o.name`` on a field the instance does not hold is the
dispatched ``__delattr__``, never an ``AttributeError`` the lift decides
(#7757 L3).

``ObjectValue.delattr`` raised ``AttributeError`` for a name no recorded
field held without asking what ``type(o).__delattr__`` is: a source
``__delattr__`` (which may swallow the delete) or a class field's own
``__delete__`` answers it in Python, so a true claim could be refuted.  The
delete is now ``type(o).__delattr__(o, name)``: where a source class of the
order binds ``__delattr__``, the dispatched call prove's one walk resolves
(``consistency::dispatch_walk``); under ``object``'s, a name no field holds
is the dispatched ``__delattr__`` as well, which no walk resolves to a raise
here; where nothing names a class, the one undecided attribute mutation
(``store_effect_sugar.undecided_attribute_mutation_faces``).

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
    # A source ``__delattr__`` swallows the delete: the constructor
    # completes.  It is stored on the class by the module, not defined in
    # its body: a ``def __delattr__`` in the body keeps the class out of the
    # constructor frame (``SourceUnit.source_class_admits_source_
    # constructor_frame``), so ``Box()`` would be the unanswered call and
    # the delete would never reach ``ObjectValue._dispatched_delattr``.
    "source-delattr-swallows-missing": (
        "def _swallow(self, name):\n"
        "    pass\n"
        "\n"
        "\n"
        "class Box:\n"
        "    def __init__(self):\n"
        "        self.x = 1\n"
        "        del self.y\n"
        "\n"
        "\n"
        "Box.__delattr__ = _swallow\n"
        "\n"
        "\n"
        "def test_box():\n"
        "    assert {claim}\n",
        "Box().x == 1",
        "Box().x == 2",
    ),
    # ``object``'s ``__delattr__`` meets a class field whose type binds
    # ``__delete__``: the descriptor answers, nothing raises.
    "class-field-descriptor-deletes-missing": (
        "class Quiet:\n"
        "    def __delete__(self, obj):\n"
        "        pass\n"
        "\n"
        "\n"
        "class Box:\n"
        "    y = Quiet()\n"
        "\n"
        "    def __init__(self):\n"
        "        self.x = 1\n"
        "        del self.y\n"
        "\n"
        "\n"
        "def test_box():\n"
        "    assert {claim}\n",
        "Box().x == 1",
        "Box().x == 2",
    ),
    # ``object``'s ``__delattr__`` on a name nothing binds: Python raises
    # ``AttributeError``, which the handler catches.
    "plain-missing-caught": (
        "class Box:\n"
        "    def __init__(self):\n"
        "        self.x = 1\n"
        "        try:\n"
        "            del self.y\n"
        "        except AttributeError:\n"
        "            self.x = 2\n"
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
def test_a_delete_of_a_missing_field_never_refutes_a_truth_nor_admits_a_lie(
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
