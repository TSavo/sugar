"""Occurrence-keyed node relational identity (#7346 Decisions A, B).

A durable semantic relation over source nodes is keyed by the SOURCE
OCCURRENCE the node denotes -- pinned source CID + exact span + node kind --
not by the Python shell that happens to view it.  ``shadow.rewrite`` mints a
fresh ShadowNode and ``materialize`` a fresh typed shell for the SAME source
occurrence (rewrite explicitly borrows the origin span), so every relation
keyed on shell identity silently loses its rows across substitution.

Two arms, which must move together:

* **A** -- ``SourceUnit.lexical_class_owner_for`` joins the producer-owned
  ``function_class_owners`` relation.
* **B** -- an ``__init__``'s receiver is its ordinary formal in every shell,
  live or overwritten, rewritten or not (#7757 B2: an ``__init__`` is an
  ordinary method, reached from a class call by the dispatched edge).

Decision C (the source ``__new__`` allocation shape admitted against
``module_direct_bindings``) is gone with the shape (#7757 A4): a source
``__new__`` is a static method the class row dispatches, never a body read
in place, so no admission of its shape remains.

Each arm carries its negative twin: a genuinely FOREIGN occurrence and a
genuinely OVERWRITTEN initializer must keep their existing answers.
Absence and lookup failure never share a representation: one row with
``owner=None`` is authenticated no-owner, zero rows stays a loud
``BackendDefect``.
"""

from __future__ import annotations

import pytest
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import (
    ClassDef,
    FormalRef,
    FunctionDef,
)
from sugar_source_tree.panic import BackendDefect
from sugar_source_tree.shadow import rewrite
from sugar_source_tree.tree import SourceFile


def _sf(source: str, name: str) -> SourceFile:
    return SourceFile((source, name, blake3_512_of(source.encode("utf-8"))))


def _fn(tree: SourceFile, name: str) -> FunctionDef:
    return next(
        n for n in tree.nodes() if isinstance(n, FunctionDef) and n.name == name
    )


_BOX = (
    "class Box:\n"
    "    def __init__(self, value):\n"
    "        self.value = value\n"
    "\n"
    "    def method(self):\n"
    "        return self.value\n"
    "\n"
    "def free(x):\n"
    "    return x\n"
)


# --------------------------------------------------------------------------
# Decision A -- the durable relation key
# --------------------------------------------------------------------------


def test_rewritten_method_joins_the_same_owner_row() -> None:
    """A rewritten shell over the same occurrence gets the producer's row."""
    tree = _sf(_BOX, "occ_owner.py")
    method = _fn(tree, "method")
    owner = tree.unit.lexical_class_owner_for(method)
    assert isinstance(owner, ClassDef) and owner.name == "Box"

    rewritten = rewrite(method)
    assert rewritten is not method
    assert rewritten.ref is not method.ref
    assert rewritten.span == method.span

    rewritten_owner = tree.unit.lexical_class_owner_for(rewritten)
    assert isinstance(rewritten_owner, ClassDef) and rewritten_owner.name == "Box"


def test_free_function_keeps_one_authenticated_no_owner_row() -> None:
    """One row with owner=None is authenticated absence, not a failed join."""
    tree = _sf(_BOX, "occ_free.py")
    free = _fn(tree, "free")
    assert tree.unit.lexical_class_owner_for(free) is None
    assert tree.unit.lexical_class_owner_for(rewrite(free)) is None


def test_foreign_occurrence_stays_a_named_refusal() -> None:
    """No span fallback: a function from another source refuses loudly."""
    tree = _sf(_BOX, "occ_home.py")
    foreign_tree = _sf("def method(self):\n    return 0\n", "occ_foreign.py")
    foreign = _fn(foreign_tree, "method")
    with pytest.raises(BackendDefect) as caught:
        tree.unit.lexical_class_owner_for(foreign)
    assert "0 backend owner rows" in caught.value.observed


# --------------------------------------------------------------------------
# Decision B -- an __init__'s receiver is its formal (#7757 B2)
# --------------------------------------------------------------------------


def test_an_initializer_s_receiver_is_its_formal_in_every_shell() -> None:
    """An ``__init__`` is an ordinary method: its receiver is its first
    formal, live or reconstructed, never a receiver its class call makes
    (the class call reaches it through the dispatched ``__init__`` edge)."""
    tree = _sf(_BOX, "occ_receiver.py")
    init = _fn(tree, "__init__")
    live = init._make_parameter_entry(init.params[0], 0, {})
    assert isinstance(live, FormalRef)

    rewritten = rewrite(init)
    reconstructed = rewritten._make_parameter_entry(rewritten.params[0], 0, {})
    assert isinstance(reconstructed, FormalRef)


_OVERWRITTEN = (
    "class Twice:\n"
    "    def __init__(self, a):\n"
    "        self.a = a\n"
    "\n"
    "    def __init__(self, b):\n"
    "        self.b = b\n"
)


def test_an_overwritten_initializer_s_receiver_is_its_formal_too() -> None:
    """Live or overwritten, each ``__init__``'s receiver is its formal."""
    tree = _sf(_OVERWRITTEN, "occ_overwritten.py")
    inits = [
        n for n in tree.nodes() if isinstance(n, FunctionDef) and n.name == "__init__"
    ]
    assert len(inits) == 2
    for init in inits:
        entry = init._make_parameter_entry(init.params[0], 0, {})
        assert isinstance(entry, FormalRef)
