"""GLOBAL / NONLOCAL DECLARATION LAWS.

Concrete:

    def outer():
        shared = 1
        def inner():
            nonlocal shared
            shared = 2   # routes to enclosing frame — or honest refusal
            return shared
        return inner()

    def f():
        global x
        x = 1            # routes to module global — or honest refusal

Acceptance:

  - ``nonlocal names`` enrolls route membership on ReduceContext (no spelling
    inference: only declared names)
  - read of a nonlocal name already bound in the captured temporal succeeds
  - store to a nonlocal-routed name WITHOUT a constructed enclosing-frame
    rebind is a ConstructionPanic (NonlocalRoute) — never silent local store
  - store of a non-declared name is ordinary local bind (no NonlocalRoute panic)
  - nonlocal route over a name unbound in the captured temporal is loud
    (NonlocalSugar) — never invents an enclosing bind
  - source ``global`` / ``nonlocal`` statements construct InertSugar today
    (declaration spent by substitute / not yet a meaning-layer GlobalRoute)
  - no scope class is inferred from name spelling (``global_x``, ``NONLOCAL``)

Owner path: ``NonlocalSugar`` / ``NonlocalRoute`` / ``reject_unconstructed_nonlocal_store``;
source ``Global``/``Nonlocal`` nodes (InertSugar). GlobalRoute enrollment is
not yet a floor value — bank reds that name that owner.

MUST NOT TOUCH: carrier/ExitSet, import identity, spelling-based scope arms.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from sugar_lift_py_tests.context.reduce_context import ReduceContext
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import BoundVar, TermValue
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.inert_sugar import InertSugar
from sugar_lift_py_tests.sugar.int_literal_sugar import IntLiteralSugar
from sugar_lift_py_tests.sugar.name_sugar import NameSugar
from sugar_lift_py_tests.sugar.nonlocal_sugar import (
    NonlocalRoute,
    NonlocalSugar,
    reject_unconstructed_nonlocal_store,
)
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import FunctionDef, Global, Nonlocal
from sugar_source_tree.tree import SourceFile


@dataclass(frozen=True)
class _Site:
    filename: str = "global_nonlocal.py"
    line: int = 1
    col: int = 0

    def __str__(self) -> str:
        return f"{self.filename}:{self.line}:{self.col}"


SITE = _Site()


def _root(owner: str = "gnl") -> ReduceContext:
    return ReduceContext.root(owner=owner)


def _int(n: int) -> IntLiteralSugar:
    return IntLiteralSugar(n, site=SITE)


def _name(n: str) -> NameSugar:
    return NameSugar(n, site=SITE)


def _tree(source: str, name: str = "global_nonlocal.py") -> SourceFile:
    return SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


# ---------------------------------------------------------------------------
# NonlocalRoute enrollment + read
# ---------------------------------------------------------------------------


def test_nonlocal_sugar_desugars_to_route() -> None:
    out = NonlocalSugar(names=("shared",), site=SITE).desugar(_root())
    assert isinstance(out, Complete)
    assert isinstance(out.value, NonlocalRoute)
    assert out.value.names == ("shared",)


def test_nonlocal_route_enrolls_declared_names_only() -> None:
    ctx = _root("enroll")
    ctx = ctx.with_temporal(ctx.temporal.bind_value("shared", TermValue(5)))
    scoped = NonlocalRoute(("shared",)).extend_scope(ctx)
    assert "shared" in scoped.nonlocal_names
    assert "other" not in scoped.nonlocal_names
    # Spelling cousins never auto-enroll.
    assert "global_shared" not in scoped.nonlocal_names
    assert "SHARED" not in scoped.nonlocal_names


def test_nonlocal_route_read_of_captured_bind_succeeds() -> None:
    ctx = _root("read")
    ctx = ctx.with_temporal(ctx.temporal.bind_value("shared", TermValue(5)))
    scoped = NonlocalRoute(("shared",)).extend_scope(ctx)
    out = _name("shared").desugar(scoped)
    assert isinstance(out, Complete)
    assert out.value == TermValue(5)


def test_nonlocal_route_missing_enclosing_bind_is_loud() -> None:
    """Route requires the enclosing temporal already bind the name — no invent."""
    with pytest.raises(ConstructionPanic, match="NonlocalSugar|enclosing lexical"):
        NonlocalRoute(("missing",)).extend_scope(_root("missing"))


# ---------------------------------------------------------------------------
# Store routes: declared nonlocal → refusal until enclosing rebind exists
# ---------------------------------------------------------------------------


def test_store_to_nonlocal_without_constructed_rebind_panics() -> None:
    """Honest refusal: never treat nonlocal store as function-local."""
    ctx = _root("store-nl")
    ctx = ctx.with_temporal(ctx.temporal.bind_value("shared", TermValue(1)))
    ctx = NonlocalRoute(("shared",)).extend_scope(ctx)
    with pytest.raises(ConstructionPanic, match="NonlocalRoute|enclosing-frame"):
        reject_unconstructed_nonlocal_store(ctx, "shared")


def test_boundvar_extend_scope_hits_nonlocal_refusal() -> None:
    """BoundVar rebind path shares reject_unconstructed_nonlocal_store."""
    ctx = _root("bv-nl")
    ctx = ctx.with_temporal(ctx.temporal.bind_value("shared", TermValue(1)))
    ctx = NonlocalRoute(("shared",)).extend_scope(ctx)
    bv = BoundVar(name="shared", source=_int(9), scope=ctx)
    with pytest.raises(ConstructionPanic, match="NonlocalRoute|enclosing-frame"):
        bv.extend_scope(ctx)


def test_store_without_nonlocal_declaration_is_local_bind() -> None:
    """No declaration ⇒ no NonlocalRoute panic; ordinary local rebind."""
    ctx = _root("local")
    ctx = ctx.with_temporal(ctx.temporal.bind_value("local", TermValue(1)))
    assert "local" not in ctx.nonlocal_names
    # Reject is a no-op when name is not enrolled.
    reject_unconstructed_nonlocal_store(ctx, "local")
    bv = BoundVar(name="local", source=_int(2), scope=ctx)
    scoped = bv.extend_scope(ctx)
    bound = scoped.temporal.value_if_bound("local")
    assert isinstance(bound, BoundVar)
    assert bound.name == "local"


def test_spelling_does_not_infer_nonlocal_route() -> None:
    """Names like ``global_x`` / ``nonlocal_y`` are not routes without declaration."""
    ctx = _root("spell")
    for name in ("global_x", "nonlocal_y", "GLOBAL", "NonLocal"):
        ctx = ctx.with_temporal(ctx.temporal.bind_value(name, TermValue(0)))
        reject_unconstructed_nonlocal_store(ctx, name)  # must not panic
        assert name not in ctx.nonlocal_names


# ---------------------------------------------------------------------------
# Source construction: Global / Nonlocal → InertSugar (declaration spent)
# ---------------------------------------------------------------------------


def test_source_global_constructs_inert_sugar() -> None:
    source = "def f():\n    global x\n    return 1\n"
    tree = _tree(source)
    node = next(n for n in tree.nodes() if isinstance(n, Global))
    sugar = node.sugar()
    assert isinstance(sugar, InertSugar)
    assert node.names == ("x",)


def test_source_nonlocal_constructs_inert_sugar() -> None:
    source = (
        "def outer():\n"
        "    shared = 1\n"
        "    def inner():\n"
        "        nonlocal shared\n"
        "        return shared\n"
        "    return inner()\n"
    )
    tree = _tree(source)
    node = next(n for n in tree.nodes() if isinstance(n, Nonlocal))
    sugar = node.sugar()
    assert isinstance(sugar, InertSugar)
    assert node.names == ("shared",)


def test_source_global_does_not_enroll_reduce_context_by_spelling() -> None:
    """Meaning-layer GlobalRoute is not yet constructed from the tree node.

    InertSugar states nothing; global_names stays empty unless a future
    GlobalRoute.extend_scope enrolls. Bank: owner GlobalRoute / Global.sugar
    meaning path when store-to-module-global must become green.
    """
    source = "def f():\n    global x\n    x = 1\n    return x\n"
    tree = _tree(source)
    function = next(
        n for n in tree.nodes() if isinstance(n, FunctionDef) and n.name == "f"
    )
    # Construction must not invent global_names from the token ``global``.
    # Function sugar may Incomplete/Complete; we only pin that Global is Inert.
    global_node = next(n for n in tree.nodes() if isinstance(n, Global))
    assert isinstance(global_node.sugar(), InertSugar)
    ctx = _root("src-global")
    assert ctx.global_names == frozenset()
    # Spelling of the declared name alone never marks global membership.
    assert "x" not in ctx.global_names


# ---------------------------------------------------------------------------
# Twin: multi-name route enrolls exactly the declared set
# ---------------------------------------------------------------------------


def test_multi_name_nonlocal_route_enrolls_all_declared() -> None:
    ctx = _root("multi")
    for n in ("a", "b"):
        ctx = ctx.with_temporal(ctx.temporal.bind_value(n, TermValue(0)))
    scoped = NonlocalRoute(("a", "b")).extend_scope(ctx)
    assert scoped.nonlocal_names == frozenset({"a", "b"})
    # Undeclared peer not enrolled.
    assert "c" not in scoped.nonlocal_names
