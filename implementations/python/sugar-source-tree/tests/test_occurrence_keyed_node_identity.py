"""Occurrence-keyed node relational identity (#7346 Decisions A, B, C).

A durable semantic relation over source nodes is keyed by the SOURCE
OCCURRENCE the node denotes -- pinned source CID + exact span + node kind --
not by the Python shell that happens to view it.  ``shadow.rewrite`` mints a
fresh ShadowNode and ``materialize`` a fresh typed shell for the SAME source
occurrence (rewrite explicitly borrows the origin span), so every relation
keyed on shell identity silently loses its rows across substitution.

Three arms, all of which must move together:

* **A** -- ``SourceUnit.lexical_class_owner_for`` joins the producer-owned
  ``function_class_owners`` relation.
* **B** -- ``FunctionDef._active_initializer_owner`` classifies the LIVE
  ``__init__`` member.  This is a policy comparison downstream of the lookup,
  so repairing A alone does not reach it.
* **C** -- ``ClassDef._authenticated_new_constructor_shape`` admits the
  source-owned ``__new__`` shape against ``module_direct_bindings``.

Each arm carries its negative twin: a genuinely FOREIGN occurrence, a
genuinely OVERWRITTEN initializer, and a genuinely SHADOWED class must keep
their existing answers.  Absence and lookup failure never share a
representation: one row with ``owner=None`` is authenticated no-owner, zero
rows stays a loud ``BackendDefect``.
"""

from __future__ import annotations

import pytest
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import (
    ClassDef,
    ConstructedReceiverRef,
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


def _cls(tree: SourceFile, name: str) -> ClassDef:
    return next(n for n in tree.nodes() if isinstance(n, ClassDef) and n.name == name)


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
# Decision B -- active-member policy
# --------------------------------------------------------------------------


def test_rewritten_active_initializer_is_still_active() -> None:
    """`active is self` cannot see a reconstructed shell of the live member."""
    tree = _sf(_BOX, "occ_active.py")
    init = _fn(tree, "__init__")
    owner = init._active_initializer_owner()
    assert isinstance(owner, ClassDef) and owner.name == "Box"

    rewritten = rewrite(init)
    rewritten_owner = rewritten._active_initializer_owner()
    assert isinstance(rewritten_owner, ClassDef), (
        "the reconstructed active __init__ denotes the same source occurrence "
        "as the member retained in owner.body"
    )
    assert rewritten_owner.name == "Box"


def test_rewritten_active_initializer_keeps_the_receiver_entrance() -> None:
    """The downstream construction delta: receiver, never an ordinary formal."""
    tree = _sf(_BOX, "occ_receiver.py")
    init = _fn(tree, "__init__")
    live = init._make_parameter_entry(init.params[0], 0, {})
    assert isinstance(live, ConstructedReceiverRef)

    rewritten = rewrite(init)
    reconstructed = rewritten._make_parameter_entry(rewritten.params[0], 0, {})
    assert isinstance(reconstructed, ConstructedReceiverRef), (
        f"reconstructed active __init__ degraded to {type(reconstructed).__name__}"
    )


_OVERWRITTEN = (
    "class Twice:\n"
    "    def __init__(self, a):\n"
    "        self.a = a\n"
    "\n"
    "    def __init__(self, b):\n"
    "        self.b = b\n"
)


def test_overwritten_initializer_stays_inactive_in_both_shells() -> None:
    """Negative twin: the shadowed __init__ is inactive, rewritten or not."""
    tree = _sf(_OVERWRITTEN, "occ_overwritten.py")
    inits = [
        n for n in tree.nodes() if isinstance(n, FunctionDef) and n.name == "__init__"
    ]
    assert len(inits) == 2
    overwritten, active = inits
    assert overwritten._active_initializer_owner() is None
    assert rewrite(overwritten)._active_initializer_owner() is None
    assert active._active_initializer_owner() is not None
    # and its ordinary formal entrance is preserved
    entry = overwritten._make_parameter_entry(overwritten.params[0], 0, {})
    assert isinstance(entry, FormalRef)


_NEW_SHAPE = (
    "class Cell:\n"
    "    def __new__(cls, value):\n"
    "        self = super(Cell, cls).__new__(cls)\n"
    "        self.value = value\n"
    "        return self\n"
)


# --------------------------------------------------------------------------
# Decision C -- authenticated __new__ admission
# --------------------------------------------------------------------------


def test_rewritten_class_keeps_authenticated_new_admission() -> None:
    """`bindings[0] is self` cannot see a reconstructed shell of the class."""
    tree = _sf(_NEW_SHAPE, "occ_new.py")
    cell = _cls(tree, "Cell")
    assert cell._authenticated_new_constructor_shape() is not None

    rewritten = rewrite(cell)
    assert rewritten._authenticated_new_constructor_shape() is not None, (
        "the reconstructed ClassDef denotes the authenticated source occurrence"
    )


def test_shadowed_class_binding_stays_unauthenticated() -> None:
    """Negative twin: two module bindings for the name -- admission refused."""
    tree = _sf(_NEW_SHAPE + "\nCell = 1\n", "occ_new_shadowed.py")
    cell = _cls(tree, "Cell")
    assert cell._authenticated_new_constructor_shape() is None
    assert rewrite(cell)._authenticated_new_constructor_shape() is None


def test_foreign_class_occurrence_stays_unauthenticated() -> None:
    """Negative twin: a same-named class from another source is not this one."""
    foreign_tree = _sf(_NEW_SHAPE, "occ_new_foreign.py")
    foreign = _cls(foreign_tree, "Cell")
    home = _sf(_NEW_SHAPE, "occ_new_home.py")
    bindings = (home.unit.module_direct_bindings or {}).get("Cell", ())
    assert len(bindings) == 1
    from sugar_source_tree.occurrence import SourceOccurrenceIdentityV1

    assert SourceOccurrenceIdentityV1.of(bindings[0]) != (
        SourceOccurrenceIdentityV1.of(foreign)
    )
