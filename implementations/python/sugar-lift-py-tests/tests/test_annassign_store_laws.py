"""ANNASSIGN STORE / DECLARATION LAWS.

Concrete:

    x: int = 1          # name + value — binding via substitute; sugar inert
    x: int              # bare name declaration — no runtime binding
    o.x: int = 1        # valued attribute — same store as ``o.x = 1``
    d[0]: int = 1       # valued subscript — same store as ``d[0] = 1``
    o.x: int            # bare attribute annotation — evaluate receiver only

Acceptance:

  - Name target + value → InertSugar; later read sees substituted value
  - Name target, no value → InertSugar; does not bind alone
  - Valued Attribute/Subscript target → AttributeStoreEffectSugar /
    SubscriptStoreEffectSugar (same store door as plain Assign)
  - Bare Attribute annotation → ExprStatementSugar of the receiver (no store)
  - Annotation is never a runtime fact (no TypeError from mismatch spelling)
  - Twins: valued attr store is not InertSugar; bare name is not a store sugar

Owner: ``AnnAssign._construct_sugar`` / ``_valued_store_target_sugar``.
No carrier/ExitSet edits; no annotation type-checking invention.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import ReturnValue, TermValue
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.expr_statement_sugar import ExprStatementSugar
from sugar_lift_py_tests.sugar.inert_sugar import InertSugar
from sugar_lift_py_tests.sugar.store_effect_sugar import (
    AttributeStoreEffectSugar,
    SubscriptStoreEffectSugar,
)
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import AnnAssign, FunctionDef
from sugar_source_tree.tree import SourceFile


def _tree(source: str, name: str = "annassign.py") -> SourceFile:
    return SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _function(source: str, *, fname: str = "f"):
    tree = _tree(source)
    return next(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name == fname
    )


def _annassigns(source: str):
    return [n for n in _tree(source).nodes() if isinstance(n, AnnAssign)]


def _return_terms(outcome) -> list:
    found = []
    if not isinstance(outcome, Complete):
        return found
    record = getattr(outcome.value, "record", outcome.value)
    for entry in getattr(record, "statements", ()) or getattr(record, "entries", ()) or ():
        if isinstance(entry, ReturnValue):
            found.append(entry.value)
    return found


# ---------------------------------------------------------------------------
# Name targets: inert declaration / substitute binding
# ---------------------------------------------------------------------------


def test_name_annassign_with_value_is_inert_and_binds_via_substitute() -> None:
    """``x: int = 1; return x`` → TermValue(1); statement sugar is InertSugar."""
    source = "def f():\n    x: int = 1\n    return x\n"
    function = _function(source)
    sugar = function.sugar()
    stmts = list(sugar.statements)
    assert any(isinstance(s, InertSugar) for s in stmts)
    assert not any(
        isinstance(s, (AttributeStoreEffectSugar, SubscriptStoreEffectSugar))
        for s in stmts
    )
    out = sugar.desugar(None)
    assert isinstance(out, Complete)
    terms = _return_terms(out)
    assert terms == [TermValue(1)], terms


def test_bare_name_annassign_is_inert_and_does_not_bind_alone() -> None:
    """``x: int`` alone introduces no binding; later assign still works."""
    source = "def f():\n    x: int\n    x = 2\n    return x\n"
    function = _function(source)
    sugar = function.sugar()
    # First statement is bare AnnAssign → InertSugar
    assert isinstance(sugar.statements[0], InertSugar)
    out = sugar.desugar(None)
    assert isinstance(out, Complete)
    assert _return_terms(out) == [TermValue(2)]


def test_bare_name_annassign_without_later_assign_leaves_name_unbound() -> None:
    """Bare ``x: int; return x`` — no value binding from the declaration.

    Unbound read is NameError (or symbolic free name) — never invent a TermValue
    from the annotation type spelling.
    """
    from sugar_lift_py_tests.effect import NameErrorEffect
    from sugar_lift_py_tests.floor import SymbolicValue
    from sugar_lift_py_tests.outcome import ExitSet, Halted
    from sugar_lift_py_tests.outcome.exit_set import outcome_to_exitset

    source = "def f():\n    x: int\n    return x\n"
    function = _function(source)
    sugar = function.sugar()
    assert isinstance(sugar.statements[0], InertSugar)
    out = outcome_to_exitset(sugar.desugar(None))
    if isinstance(out, ExitSet):
        halted = [e for e in out.exits if isinstance(e, Halted)]
        assert halted, out.exits
        assert any(isinstance(e.effect, NameErrorEffect) for e in halted), halted
        return
    # Alternate face: Complete with SymbolicValue free name (no TermValue invent).
    assert isinstance(out, Complete)
    terms = _return_terms(out)
    assert not any(isinstance(t, TermValue) for t in terms), terms
    assert any(isinstance(t, SymbolicValue) for t in terms), terms


# ---------------------------------------------------------------------------
# Valued store targets: same door as Assign
# ---------------------------------------------------------------------------


def test_valued_attribute_annassign_constructs_attribute_store() -> None:
    """``o.x: int = 1`` is AttributeStoreEffectSugar, not InertSugar."""
    source = "def f(o):\n    o.x: int = 1\n    return o\n"
    function = _function(source)
    sugar = function.sugar()
    stores = [s for s in sugar.statements if isinstance(s, AttributeStoreEffectSugar)]
    assert len(stores) == 1, [type(s).__name__ for s in sugar.statements]
    assert stores[0].attr == "x"
    assert not any(isinstance(s, InertSugar) for s in sugar.statements if type(s).__name__ == "AttributeStoreEffectSugar")


def test_valued_subscript_annassign_constructs_subscript_store() -> None:
    """``d[0]: int = 1`` is SubscriptStoreEffectSugar."""
    source = "def f(d):\n    d[0]: int = 1\n    return d\n"
    function = _function(source)
    sugar = function.sugar()
    stores = [s for s in sugar.statements if isinstance(s, SubscriptStoreEffectSugar)]
    assert len(stores) == 1, [type(s).__name__ for s in sugar.statements]


def test_valued_attribute_annassign_matches_plain_assign_store_kind() -> None:
    """AnnAssign and Assign attribute stores share AttributeStoreEffectSugar."""
    ann = _function("def f(o):\n    o.x: int = 1\n    return 0\n").sugar()
    plain = _function("def f(o):\n    o.x = 1\n    return 0\n").sugar()
    ann_store = next(s for s in ann.statements if isinstance(s, AttributeStoreEffectSugar))
    plain_store = next(
        s for s in plain.statements if isinstance(s, AttributeStoreEffectSugar)
    )
    assert type(ann_store) is type(plain_store)
    assert ann_store.attr == plain_store.attr == "x"


# ---------------------------------------------------------------------------
# Bare attribute annotation: receiver only
# ---------------------------------------------------------------------------


def test_bare_attribute_annotation_is_receiver_expression_statement() -> None:
    """``o.x: int`` evaluates the receiver ``o`` only — no attribute store."""
    source = "def f(o):\n    o.x: int\n    return 0\n"
    function = _function(source)
    sugar = function.sugar()
    assert any(isinstance(s, ExprStatementSugar) for s in sugar.statements), [
        type(s).__name__ for s in sugar.statements
    ]
    assert not any(
        isinstance(s, AttributeStoreEffectSugar) for s in sugar.statements
    )


# ---------------------------------------------------------------------------
# Twins / discrimination
# ---------------------------------------------------------------------------


def test_name_annassign_value_vs_bare_same_inert_class() -> None:
    """Both name forms are InertSugar; discrimination is presence of later bind."""
    with_val = _function("def f():\n    x: int = 1\n    return x\n").sugar()
    bare = _function("def f():\n    x: int\n    return 0\n").sugar()
    assert isinstance(with_val.statements[0], InertSugar)
    assert isinstance(bare.statements[0], InertSugar)
    assert _return_terms(with_val.desugar(None)) == [TermValue(1)]
    assert _return_terms(bare.desugar(None)) == [TermValue(0)]


def test_annassign_node_exposes_annotation_and_simple_flag() -> None:
    """Tree testimony: annotation present; simple Name flag when applicable."""
    nodes = _annassigns("def f():\n    x: int = 1\n    return x\n")
    assert len(nodes) == 1
    assert nodes[0].value is not None
    assert bool(nodes[0].simple)  # tree may store 0/1
    assert nodes[0].annotation is not None
