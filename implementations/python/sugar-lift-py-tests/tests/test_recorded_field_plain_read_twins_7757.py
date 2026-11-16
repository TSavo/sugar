"""Twins: a recorded instance field is read as that field only where prove
decides the read is the instance's ``__dict__`` entry (#7757).

``ObjectValue.attribute`` answered ``self.x`` from the instance's recorded
fields on every current instance.  It never asked whether a class of the
order binds ``__getattribute__`` (which runs on every read), nor whether a
class binds a data descriptor of the name (which wins over the instance
``__dict__``).  For

    class Shadow:
        def __init__(self):
            self.x = 1

        def __getattribute__(self, name):
            return 99

Python reads ``o.x`` as ``99``.  The recorded field is now stated only
under ``python:plain_read(<class>, "x")`` -- the atom a constructed field's
read already takes (#9051), decided by prove alone on the namespace rows
(``consistency::plain_read_holds``: no read hook in the order, no binding
of the name) -- and under its complement the read is the dispatched read.

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

# ``__getattribute__`` runs on every read: ``x`` and ``y`` read ``99``.
_HOOKED = (
    "class Shadow:\n"
    "    def __init__(self):\n"
    "        self.x = 1\n"
    "        self.y = self.x\n"
    "\n"
    "    def __getattribute__(self, name):\n"
    "        return 99\n"
    "\n"
    "\n"
    "def test_shadow():\n"
    "    o = Shadow()\n"
    "    assert {claim}\n"
)

# A class data descriptor of ``x`` wins over the instance ``__dict__``:
# ``self.x = 1`` runs ``__set__`` and ``self.x`` reads ``__get__``'s 99.
_DESCRIPTOR = (
    "class Ninety:\n"
    "    def __get__(self, obj, owner):\n"
    "        return 99\n"
    "\n"
    "    def __set__(self, obj, value):\n"
    "        pass\n"
    "\n"
    "\n"
    "class Holder:\n"
    "    x = Ninety()\n"
    "\n"
    "    def __init__(self):\n"
    "        self.x = 1\n"
    "        self.y = self.x\n"
    "\n"
    "\n"
    "def test_holder():\n"
    "    o = Holder()\n"
    "    assert {claim}\n"
)

# No hook and no binding of the name: the read is the recorded field.
_PLAIN = (
    "class Plain:\n"
    "    def __init__(self):\n"
    "        self.x = 1\n"
    "        self.y = self.x\n"
    "\n"
    "\n"
    "def test_plain():\n"
    "    o = Plain()\n"
    "    assert {claim}\n"
)

# ``name: (source, claim, half)``.
_CASES = {
    "getattribute-field-lying": (_HOOKED, "o.x == 1", "lying"),
    "getattribute-field-truthful": (_HOOKED, "o.x == 99", "truthful"),
    "getattribute-derived-field-lying": (_HOOKED, "o.y == 1", "lying"),
    "descriptor-derived-field-lying": (_DESCRIPTOR, "o.y == 1", "lying"),
    "descriptor-derived-field-truthful": (_DESCRIPTOR, "o.y == 99", "truthful"),
    "plain-derived-field-truthful": (_PLAIN, "o.y == 1", "truthful"),
    "plain-derived-field-lying": (_PLAIN, "o.y == 2", "lying"),
}


def _claims_line(source: str) -> int:
    """The line of the test function's ``def``: it follows the classes."""
    for number, line in enumerate(source.splitlines(), start=1):
        if line.startswith("def test_"):
            return number
    raise AssertionError("the source states no test function")


@pytest.mark.parametrize("case", sorted(_CASES))
def test_a_recorded_field_read_never_refutes_a_truth_nor_admits_a_lie(
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


def test_a_recorded_field_is_the_value_only_under_plain_read(tmp_path: Path) -> None:
    """The lift states the recorded ``1`` only on the face prove's
    ``python:plain_read`` holds on; its complement is the dispatched read,
    which keeps its halt.  No face reads ``1`` outright, hook or not."""
    from frame_fresh import FRAME_FRESH

    from sugar_lift_py_tests.context.reduce_context import ReduceContext
    from sugar_lift_py_tests.floor import ObjectField, TermValue
    from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
    from sugar_lift_py_tests.outcome import Completed
    from sugar_source_tree.nodes import ClassDef

    path = tmp_path / "recorded_field.py"
    path.write_text(_HOOKED.format(claim="True"))
    tree = open_source_file_for_construction(path, root=tmp_path)
    statement = next(
        node
        for node in tree.root.body
        if isinstance(node, ClassDef) and node.name == "Shadow"
    )
    ctx = ReduceContext.root(owner="test")
    value = statement.sugar().desugar(ctx).completed_value()
    receiver = value.fresh_receiver("receiver-cid", allocation=FRAME_FRESH)
    receiver = receiver.with_field_store("x", TermValue(1))

    outcome = receiver.attribute("x", "x-site", ctx)

    assert outcome.halts(), outcome
    completed = [face for face in outcome.exits if isinstance(face, Completed)]
    ones = [face for face in completed if face.value == TermValue(1)]
    assert len(ones) == 1, completed
    assert "python:plain_read" in repr(ones[0].guard)
    assert ObjectField("x", TermValue(1)) in receiver.fields
