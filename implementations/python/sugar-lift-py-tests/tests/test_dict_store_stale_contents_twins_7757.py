"""Twins: a store into a dict whose contents are not current is the one
undecided item mutation (#7757).

``DictValue.setitem`` once read whether the key is held -- overwrite in
place, or append -- off the entries the value carries even when they are
not the dict's contents now (``object_identity.contents_current``): a dict
read through a module global or an instance's field arrives by binding, and
code this frame does not see may have changed it since.  The store wrote
into those stale entries, and completed with no raise face, though a stored
key's ``==`` against the new key may raise.  ``DictValue.delitem`` already
read only current entries; the store now does too: on contents that are not
current it is ``store_effect_sugar.undecided_item_mutation_faces``, whose
completed value is the receiver's unknown after-state
(``python:receiver_after_call``) and whose complement halts with an
undetermined raise.

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
    "global-dict-store-held-key": (
        '_D = {{"a": 1}}\n'
        "\n"
        "\n"
        "def g():\n"
        '    _D["a"] = 2\n'
        '    return _D["a"]\n'
        "\n"
        "\n"
        "def test_g():\n"
        "    assert {claim}\n",
        "g() == 2",
        "g() == 1",
    ),
    "field-dict-store-held-key": (
        "class Box:\n"
        "    def __init__(self):\n"
        '        self.d = {{"a": 1}}\n'
        "\n"
        "\n"
        "def g():\n"
        "    box = Box()\n"
        "    d = box.d\n"
        '    d["a"] = 2\n'
        "    return len(d)\n"
        "\n"
        "\n"
        "def test_g():\n"
        "    assert {claim}\n",
        "g() == 1",
        "g() == 2",
    ),
}


def _claims_line(source: str) -> int:
    """The line of the test function's ``def``: it follows the helper."""
    for number, line in enumerate(source.splitlines(), start=1):
        if line.startswith("def test_"):
            return number
    raise AssertionError("the source states no test function")


@pytest.mark.parametrize("half", ["truthful", "lying"])
@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_a_store_into_stale_dict_contents_never_refutes_a_truth_nor_admits_a_lie(
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
