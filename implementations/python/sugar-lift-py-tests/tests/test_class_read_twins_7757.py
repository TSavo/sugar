"""Twins: a class-field value read off an instance is that value only where
prove decides the read is the class's binding (#7757 L1).

``ObjectValue.attribute`` answered ``o.limit`` from the class body's
binding (``class_member``) on every current instance.  It never asked
whether a class of the order binds ``__getattribute__``, nor whether the
value's class defines ``__get__``: for

    class Shadow:
        limit = 1

        def __getattribute__(self, name):
            return 2

it read ``limit`` as ``1``, although Python runs ``__getattribute__`` and
reads ``2``; and ``limit = Ten()`` with ``Ten.__get__`` read as the
descriptor object, not what ``__get__`` returns.  The value is now stated
only under ``python:class_read(<class>, "limit")``, which prove alone
decides on the namespace rows (``consistency::class_read_holds``: no read
hook in the order, and the binding a literal or display, kind ``value``);
under its complement the read is the dispatched read.

The value on that face is the binding's object as it arrives in the reading
frame, never the contents the class body gave it (#7757 L3): ``items = [1]``
read as ``self.items`` after ``Box.items.append(2)`` had ``len`` 1 decided.
A class-level list, dict or set is now read by identity, as every stale
container is (#9087).

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

# ``__getattribute__`` runs on every read: ``limit`` reads ``2``, never the
# class body's ``1``.
_HOOKED = (
    "class Shadow:\n"
    "    limit = 1\n"
    "\n"
    "    def __getattribute__(self, name):\n"
    "        return 2\n"
    "\n"
    "\n"
    "def test_shadow():\n"
    "    assert {claim}\n"
)

# A descriptor-valued field: the read is what ``Ten.__get__`` returns.
_DESCRIPTOR = (
    "class Ten:\n"
    "    def __get__(self, obj, owner):\n"
    "        return 10\n"
    "\n"
    "\n"
    "class Holder:\n"
    "    limit = Ten()\n"
    "\n"
    "\n"
    "def test_holder():\n"
    "    assert {claim}\n"
)

# A plain literal field and no hook: the read is the value.
_PLAIN = (
    "class Plain:\n"
    "    limit = 1\n"
    "\n"
    "\n"
    "def test_plain():\n"
    "    assert {claim}\n"
)

# ``name: (source, claim, half)``.
_CASES = {
    "getattribute-class-field-lying": (_HOOKED, "Shadow().limit == 1", "lying"),
    "getattribute-class-field-truthful": (_HOOKED, "Shadow().limit == 2", "truthful"),
    "descriptor-class-field-lying": (_DESCRIPTOR, "Holder().limit != 10", "lying"),
    "descriptor-class-field-truthful": (_DESCRIPTOR, "Holder().limit == 10", "truthful"),
    "plain-class-field-truthful": (_PLAIN, "Plain().limit == 1", "truthful"),
    "plain-class-field-lying": (_PLAIN, "Plain().limit == 2", "lying"),
}


def _claims_line(source: str) -> int:
    """The line of the test function's ``def``: it follows the classes."""
    for number, line in enumerate(source.splitlines(), start=1):
        if line.startswith("def test_"):
            return number
    raise AssertionError("the source states no test function")


@pytest.mark.parametrize("case", sorted(_CASES))
def test_a_class_field_read_never_refutes_a_truth_nor_admits_a_lie(
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


def _rooted_class(tmp_path: Path, source: str, name: str):
    from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
    from sugar_source_tree.nodes import ClassDef

    path = tmp_path / "class_read.py"
    path.write_text(source)
    tree = open_source_file_for_construction(path, root=tmp_path)
    return next(
        node
        for node in tree.root.body
        if isinstance(node, ClassDef) and node.name == name
    )


def test_the_namespace_row_states_a_literal_field_as_a_value(tmp_path: Path) -> None:
    """A literal or display is kind ``value`` (its class defines no
    ``__get__``); a call's result, which may be a descriptor, stays
    ``other``."""
    from sugar_lift_py_tests.tree_enumerate import _class_namespace_facts

    source = (
        "class Ten:\n"
        "    def __get__(self, obj, owner):\n"
        "        return 10\n"
        "\n"
        "\n"
        "class Box:\n"
        "    limit = 1\n"
        "    pair = (1, 2)\n"
        "    names: dict = {}\n"
        "    ten = Ten()\n"
    )
    _symbol, _mro, binds, _object = _class_namespace_facts(
        _rooted_class(tmp_path, source, "Box")
    )
    kinds = {name: (kind, target) for name, kind, target in binds}
    assert kinds["limit"] == ("value", "")
    assert kinds["pair"] == ("value", "")
    assert kinds["names"] == ("value", "")
    assert kinds["ten"] == ("other", "")


def test_a_class_field_read_is_the_value_only_under_class_read(tmp_path: Path) -> None:
    """The lift states ``limit``'s ``1`` only on the face prove's
    ``python:class_read`` holds on; its complement is the dispatched read,
    which keeps its halt.  No face reads ``1`` outright."""
    from frame_fresh import FRAME_FRESH

    from sugar_lift_py_tests.context.reduce_context import ReduceContext
    from sugar_lift_py_tests.floor import TermValue
    from sugar_lift_py_tests.outcome import Completed

    statement = _rooted_class(tmp_path, _HOOKED.format(claim="True"), "Shadow")
    ctx = ReduceContext.root(owner="test")
    value = statement.sugar().desugar(ctx).completed_value()
    receiver = value.fresh_receiver("receiver-cid", allocation=FRAME_FRESH)

    outcome = receiver.attribute("limit", "limit-site", ctx)

    assert outcome.halts(), outcome
    completed = [face for face in outcome.exits if isinstance(face, Completed)]
    ones = [face for face in completed if face.value == TermValue(1)]
    assert len(ones) == 1, completed
    assert "python:class_read" in repr(ones[0].guard)


# ---------------------------------------------------------------------------
# A class-level container is read by identity, never by the contents the
# class body gave it (#7757 L3)
# ---------------------------------------------------------------------------

# ``grow`` appends to the class's list before the constructor reads it:
# ``len(self.items)`` is 2, never the class body's 1.
_MUTATED_LIST = (
    "class Box:\n"
    "    items = [1]\n"
    "\n"
    "    def __init__(self):\n"
    "        self.n = len(self.items)\n"
    "\n"
    "\n"
    "def grow():\n"
    "    Box.items.append(2)\n"
    "\n"
    "\n"
    "def made():\n"
    "    grow()\n"
    "    return Box().n\n"
    "\n"
    "\n"
    "def test_box():\n"
    "    assert {claim}\n"
)

# ``poke`` stores into the class's dict before the constructor reads it:
# ``self.entries["a"]`` is 5, never the class body's 1.
_MUTATED_DICT = (
    "class Table:\n"
    "    entries = {{'a': 1}}\n"
    "\n"
    "    def __init__(self):\n"
    "        self.v = self.entries['a']\n"
    "\n"
    "\n"
    "def poke():\n"
    "    Table.entries['a'] = 5\n"
    "\n"
    "\n"
    "def made():\n"
    "    poke()\n"
    "    return Table().v\n"
    "\n"
    "\n"
    "def test_table():\n"
    "    assert {claim}\n"
)

# ``name: (source, claim, half)``.
_CONTAINER_CASES = {
    "class-list-mutated-lying": (_MUTATED_LIST, "made() == 1", "lying"),
    "class-list-mutated-truthful": (_MUTATED_LIST, "made() == 2", "truthful"),
    "class-dict-mutated-lying": (_MUTATED_DICT, "made() == 1", "lying"),
    "class-dict-mutated-truthful": (_MUTATED_DICT, "made() == 5", "truthful"),
}


@pytest.mark.parametrize("case", sorted(_CONTAINER_CASES))
def test_a_class_level_container_read_never_refutes_a_truth_nor_admits_a_lie(
    tmp_path: Path, case: str
) -> None:
    source, claim, half = _CONTAINER_CASES[case]
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


def test_a_class_level_list_arrives_by_identity(tmp_path: Path) -> None:
    """The face ``python:class_read`` holds on carries the class's list as
    the object it is, its contents not current: a read of them is the
    read's undecided form over its identity (#9087), never the class body's
    ``[1]``."""
    from frame_fresh import FRAME_FRESH

    from sugar_lift_py_tests.context.reduce_context import ReduceContext
    from sugar_lift_py_tests.floor.list_value import ListValue
    from sugar_lift_py_tests.floor.object_identity import contents_current
    from sugar_lift_py_tests.outcome import Completed

    statement = _rooted_class(
        tmp_path, "class Box:\n    items = [1]\n", "Box"
    )
    ctx = ReduceContext.root(owner="test")
    value = statement.sugar().desugar(ctx).completed_value()
    receiver = value.fresh_receiver("receiver-cid", allocation=FRAME_FRESH)

    outcome = receiver.attribute("items", "items-site", ctx)

    completed = [face for face in outcome.exits if isinstance(face, Completed)]
    (face,) = [face for face in completed if isinstance(face.value, ListValue)]
    assert "python:class_read" in repr(face.guard)
    assert not contents_current(face.value), face.value
    assert face.value.arrival is not None, face.value
