"""SIN CLUSTER 6 — enumeration that bypasses the construction door.

Coordinates under sugar-lift-py-tests:

1. applied_contract_rows binds through SourceCallFrame.bind_node_actuals
   (not ad-hoc zip of flat params). ``f(a, *rest)`` called ``f(1, 2)`` packs
   ``rest=(2,)``; a lying twin asserting ``rest=2`` must fail.
2. No second bare FunctionUniverseSugar mint — formal coordinates come from
   the frame produced by the construction door.
3. Function resolution is binding/coordinate, not first-match-by-spelling;
   a miss THROWS FunctionBindingMiss (named), never soft None.
"""

from __future__ import annotations

import inspect

import pytest

from sugar_lift_py_tests import tree_enumerate as te
from sugar_lift_py_tests.source_call_frame import SourceCallBindingGap
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.nodes import Call, Constant, FunctionDef, Name
from sugar_source_tree.tree import SourceFile


def _tree(source: str, name: str = "cluster6.py") -> SourceFile:
    return SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _module_fn(source: str, name: str) -> tuple[SourceFile, FunctionDef]:
    tree = _tree(source)
    list(tree.functions())  # force bind-time rosters
    fn = te.find_function_by_name(tree, name)
    return tree, fn


# --- 1 + 2: bind_node_actuals door; no second bare FunctionUniverseSugar -----


def test_variadic_applied_binds_rest_as_tuple_truthful_twin() -> None:
    """Truthful: ``f(a, *rest)`` called ``f(1, 2)`` binds rest as Tuple(2,)."""
    source = (
        "def f(a, *rest):\n"
        "    return rest\n"
        "\n"
        "def test_a():\n"
        "    assert f(1, 2) == (2,)\n"
    )
    tree, fn = _module_fn(source, "f")
    call = next(
        node
        for node in tree.nodes()
        if isinstance(node, Call)
        and isinstance(node.func, Name)
        and node.func.id == "f"
    )
    frame = fn.source_visible_call_frame()
    bound = frame.bind_node_actuals(tuple(call.args), ())
    by_name = {
        name: entry.state
        for name, entry in zip(bound.parameters, bound.runtime_entries, strict=True)
    }
    rest = by_name["rest"]
    # Materialized Tuple may be the shadow class (``Tuple_``); kind is authority.
    assert rest.kind == "Tuple", type(rest).__name__
    assert len(rest.elts) == 1
    assert rest.elts[0].kind == "Constant"
    assert rest.elts[0].value == 2

    # Applied contract path uses the same door and publishes without minting a
    # coordinate-free FunctionUniverseSugar.
    _memento, rows = te.applied_contract_rows(fn, tuple(call.args), "cluster6.py")
    assert rows is not None


def test_variadic_applied_lying_twin_rest_is_not_scalar_must_fail() -> None:
    """Lying twin: asserting rest is the bare scalar 2 must fail.

    The old ad-hoc binder ``zip(params, args)`` published rest=2. That shape
    is illegal; the twin fails so the regression cannot go silent.
    """
    source = (
        "def f(a, *rest):\n"
        "    return rest\n"
        "\n"
        "def test_a():\n"
        "    assert f(1, 2) == (2,)\n"
    )
    tree, fn = _module_fn(source, "f")
    call = next(
        node
        for node in tree.nodes()
        if isinstance(node, Call)
        and isinstance(node.func, Name)
        and node.func.id == "f"
    )
    frame = fn.source_visible_call_frame()
    bound = frame.bind_node_actuals(tuple(call.args), ())
    rest = dict(
        zip(bound.parameters, (e.state for e in bound.runtime_entries), strict=True)
    )["rest"]

    # Truthful: packed Tuple. Lying: bare Constant(2) — must not hold.
    assert rest.kind == "Tuple"
    with pytest.raises(AssertionError):
        assert rest.kind == "Constant" and rest.value == 2


def test_applied_contract_rows_does_not_mint_bare_function_universe_sugar() -> None:
    """Coordinate 2: source must not construct FunctionUniverseSugar inline."""
    src = inspect.getsource(te.applied_contract_rows)
    assert "FunctionUniverseSugar(" not in src
    assert "bind_node_actuals" in src
    assert "formal_coordinates" in src


def test_ad_hoc_zip_binder_is_absent_from_applied_contract_rows() -> None:
    """Coordinate 1 instrument: the flat param/actual zip binder is gone."""
    src = inspect.getsource(te.applied_contract_rows)
    # Executable body only — docstring may name the retired shape.
    body = src.split('"""', 2)[-1] if '"""' in src else src
    assert "zip(fn.params" not in body
    assert "{p.name: a for p, a in zip" not in body


def test_bind_actuals_floor_packs_rest_as_tuple_value() -> None:
    """Floor side of the same door: bind_actuals packs *rest into TupleValue."""
    from sugar_lift_py_tests.floor import TermValue, TupleValue

    source = "def f(a, *rest):\n    return rest\n"
    _tree_sf, fn = _module_fn(source, "f")
    frame = fn.source_visible_call_frame()
    bound = frame.bind_actuals((TermValue(1), TermValue(2)), ())
    assert len(bound.actuals) == 2
    rest = bound.actuals[1]
    assert rest == TupleValue((TermValue(2),))
    with pytest.raises(AssertionError):
        # Lying twin: rest is the bare second actual, not a pack.
        assert rest == TermValue(2)


def test_binding_gap_is_loud_on_arity_mismatch() -> None:
    """No silent truncate: missing required formal raises SourceCallBindingGap."""
    source = "def f(a, b):\n    return a\n"
    _tree_sf, fn = _module_fn(source, "f")
    frame = fn.source_visible_call_frame()
    with pytest.raises(SourceCallBindingGap):
        frame.bind_node_actuals((), ())


# --- 3: binding/coordinate resolution; named throw on miss -------------------


def test_find_function_by_name_module_binding_truthful_twin() -> None:
    source = (
        "class C:\n"
        "    def f(self):\n"
        "        return 0\n"
        "\n"
        "def f(a, *rest):\n"
        "    return rest\n"
    )
    tree = _tree(source)
    list(tree.functions())
    fn = te.find_function_by_name(tree, "f")
    assert isinstance(fn, FunctionDef)
    assert fn.name == "f"
    # Module-level def, not the method: has *rest.
    assert any(p.param_kind == "vararg" for p in fn.params)


def test_find_function_by_name_miss_throws_named() -> None:
    source = "def g():\n    return 1\n"
    tree = _tree(source)
    list(tree.functions())
    with pytest.raises(te.FunctionBindingMiss) as caught:
        te.find_function_by_name(tree, "missing")
    assert caught.value.name == "missing"
    assert "no module-direct" in caught.value.reason


def test_find_function_by_name_does_not_return_none_on_miss() -> None:
    """Lying twin of soft-None: the miss path must not be a None result."""
    source = "def g():\n    return 1\n"
    tree = _tree(source)
    list(tree.functions())
    try:
        result = te.find_function_by_name(tree, "nope")
    except te.FunctionBindingMiss:
        return
    # If we got here without throw, soft None is the SIN.
    assert result is not None, "miss returned None — absence must THROW named"


def test_resolve_function_for_call_by_coordinate() -> None:
    source = (
        "def helper(x):\n"
        "    return x\n"
        "\n"
        "def test_a():\n"
        "    assert helper(3) == 3\n"
    )
    tree = _tree(source)
    list(tree.functions())
    call = next(
        node
        for node in tree.nodes()
        if isinstance(node, Call)
        and isinstance(node.func, Name)
        and node.func.id == "helper"
    )
    fn = te.resolve_function_for_call(call)
    assert fn.name == "helper"
    assert fn is te.find_function_by_name(tree, "helper")


def test_resolve_function_for_call_miss_throws_named() -> None:
    source = "def test_a():\n" "    assert unknown_callee(1) == 1\n"
    tree = _tree(source)
    list(tree.functions())
    call = next(
        node
        for node in tree.nodes()
        if isinstance(node, Call)
        and isinstance(node.func, Name)
        and node.func.id == "unknown_callee"
    )
    with pytest.raises(te.FunctionBindingMiss) as caught:
        te.resolve_function_for_call(call)
    assert caught.value.name == "unknown_callee"


def test_spelling_first_match_over_methods_is_not_authority() -> None:
    """Class method spelling must not win over the module-direct binding."""
    source = (
        "class Holder:\n"
        "    def pack(self, *items):\n"
        "        return items\n"
        "\n"
        "def pack(a, *rest):\n"
        "    return (a, rest)\n"
        "\n"
        "def test_a():\n"
        "    assert pack(1, 2) == (1, (2,))\n"
    )
    tree = _tree(source)
    list(tree.functions())
    fn = te.find_function_by_name(tree, "pack")
    # Module def has formals (a, *rest); method has (self, *items).
    assert [p.name for p in fn.params] == ["a", "rest"]


def test_applied_contract_ground_list_fold_truthful_twin() -> None:
    """Unit twin of dig-with-args: ground list folds through bind_node_actuals door."""
    source = (
        "def A(xs):\n"
        "    total = 0\n"
        "    for x in xs:\n"
        "        total = total + x\n"
        "    return total\n"
        "\n"
        "def test_a():\n"
        "    assert A([1, 2, 3]) == 6\n"
    )
    tree, fn = _module_fn(source, "A")
    call = next(
        node
        for node in tree.nodes()
        if isinstance(node, Call)
        and isinstance(node.func, Name)
        and node.func.id == "A"
    )
    _memento, rows = te.applied_contract_rows(fn, tuple(call.args), "fold.py")
    assert rows is not None
    post = rows[0].post
    assert post is not None
    # out == 6 after the fold collapses under applied actuals.
    formula = post.ir_formula
    # Formula is (= out 6) or equivalent tree; walk for the literal 6.
    text = str(formula)
    assert "6" in text
