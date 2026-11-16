"""Twins: ``self.pop(k, d)`` on a ``dict`` subclass is the dispatched call,
never ``dict.pop`` the lift answers from the instance's base storage
(#7757 H3, NEW-10).

``PathContainerCallSugar`` answered ``pop(k, d)`` on a ``MappingObjectValue``
(the arrived ``self`` of a ``dict`` subclass's initializer) at lift
(``_inherited_mapping_pop``, ``mapping_pop_result``/``mapping_pop_state``).
It decided ``pop`` was ``dict.pop`` by scanning the class's fields, which a
source ``def pop`` is not, and it read the base storage, which is never
current (``MappingObjectValue._builtin_dict``) and holds no entries on an
arrived ``self``.  So ``x = self.pop(k, d)`` was always ``d``: the claim on
``d`` could read ``sat`` whatever the dict held and whatever ``pop`` the
class defined.  The call is now the ordinary call: the dispatched member
prove's one walk decides.

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

# ``name: (source, truthful claim, lying claim)``.  Braces are doubled: the
# source is a ``str.format`` template.
_SHAPES = {
    # The class defines ``pop``: Python calls it, and ``v`` is 7.  The lift
    # used to answer ``dict.pop``'s default, 0.
    "source-pop-overrides-dict-pop": (
        "class M(dict):\n"
        "    def __init__(self):\n"
        '        x = self.pop("k", 0)\n'
        "        self.v = x\n"
        "\n"
        "    def pop(self, key, default):\n"
        "        return 7\n"
        "\n"
        "\n"
        "def test_m():\n"
        "    assert {claim}\n",
        "M().v == 7",
        "M().v == 0",
    ),
    # The inherited ``dict.pop`` on a dict that holds the key: Python pops
    # 5.  The lift read the arrived ``self``'s empty storage and answered 0.
    "inherited-pop-of-a-held-key": (
        "class M(dict):\n"
        "    def __init__(self, **kw):\n"
        "        super().__init__(**kw)\n"
        '        x = self.pop("k", 0)\n'
        "        self.v = x\n"
        "\n"
        "\n"
        "def test_m():\n"
        "    assert {claim}\n",
        "M(k=5).v == 5",
        "M(k=5).v == 0",
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
def test_a_dict_subclass_pop_never_refutes_a_truth_nor_admits_a_lie(
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
