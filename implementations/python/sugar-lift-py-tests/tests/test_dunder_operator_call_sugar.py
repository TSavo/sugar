"""Explicit dunder-operator Call bridge (#5912): ``x.__mul__(y)`` etc routed
through the SAME floor verbs the ``BinOp``-family Sugars already call.

Truthful/lying twins prove the bridge computes the right answer; the lying
twins below are the ones that must REFUTE (never match this Sugar, or match
and disagree with the operator semantics)."""

from __future__ import annotations

import ast

import pytest
from factory_reduce import reduce_value

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory import FactoryPanic
from sugar_lift_py_tests.sugar.dunder_operator_call_sugar import (
    DunderOperatorCallSugar,
)
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver
from sugar_lift_py_tests.floor import SymbolicValue
from sugar_lift_py_tests.ir import make_var


def _selected(expr: str) -> str:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse(expr, mode="eval").body
    result = build_node(node, filename="t.py", role=SugarRole.TERM, ctx=ctx)
    return result.audit_row.selected


# ---------------------------------------------------------------------------
# Truthful: the bridge folds explicit dunder calls to the same value the
# operator spelling would.
# ---------------------------------------------------------------------------


def test_explicit_mul_dunder_call_selects_the_bridge() -> None:
    assert _selected("(5).__mul__(3)") == "DunderOperatorCallSugar"


def test_explicit_mul_dunder_call_folds_like_the_operator() -> None:
    assert reduce_value("(5).__mul__(3)").value == reduce_value("5 * 3").value


def test_explicit_add_dunder_call_folds_like_the_operator() -> None:
    assert reduce_value("(5).__add__(2)").value == reduce_value("5 + 2").value


def test_explicit_sub_dunder_call_folds_like_the_operator() -> None:
    assert reduce_value("(5).__sub__(2)").value == reduce_value("5 - 2").value


def test_explicit_truediv_dunder_call_folds_like_the_operator() -> None:
    assert reduce_value("(6).__truediv__(2)").value == reduce_value("6 / 2").value


def test_explicit_floordiv_dunder_call_folds_like_the_operator() -> None:
    assert reduce_value("(7).__floordiv__(2)").value == reduce_value("7 // 2").value


def test_explicit_getitem_dunder_call_folds_like_the_subscript() -> None:
    assert reduce_value("[10, 20, 30].__getitem__(1)").value == reduce_value(
        "[10, 20, 30][1]"
    ).value


# ---------------------------------------------------------------------------
# The unclassified factory-walk row itself (#5252 / #5912): on a SYMBOLIC
# receiver/operand (the shape every recensus row is -- a free variable, not a
# ground literal) the bridged call must emit the SAME recognized operator
# ctor term the `BinOp`/`Subscript` spelling emits (``+``, ``*``, ``//``,
# ``py.subscript``, ...), never the opaque unresolved ``call:__dunder__``
# CallSiteValue coordinate MethodCallSugar's generic fallback produces for
# anything it cannot open a body for. The opaque ``call:`` coordinate IS the
# unclassified residue this bridge drains; this asserts it is gone.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "member_ticket,expr,expected_ctor_name",
    [
        ("5761 call:__add__", "x.__add__(y)", "+"),
        ("5822 call:__sub__", "x.__sub__(y)", "-"),
        ("5821 call:__mul__", "x.__mul__(y)", "*"),
        ("5823 call:__truediv__", "x.__truediv__(y)", "/"),
        ("5820 call:__floordiv__", "x.__floordiv__(y)", "//"),
        # __rfloordiv__(y) means y // x -- still the SAME "//" ctor, never a
        # bare unresolved call: coordinate.
        ("5663 call:__rfloordiv__", "x.__rfloordiv__(y)", "//"),
    ],
)
def test_member_ticket_shape_emits_recognized_operator_ctor(
    member_ticket, expr, expected_ctor_name
) -> None:
    from factory_reduce import reduce_term

    term = reduce_term(
        expr,
        binds={
            "x": SymbolicValue(make_var("x")),
            "y": SymbolicValue(make_var("y")),
        },
    )
    assert term.name == expected_ctor_name, (
        f"{member_ticket}: expected recognized ctor `{expected_ctor_name}`, "
        f"got `{term.name}` (opaque call: coordinate == still unclassified)"
    )
    assert not term.name.startswith("call:"), member_ticket


def test_member_ticket_getitem_shape_emits_recognized_subscript_ctor() -> None:
    from factory_reduce import reduce_term
    from sugar_lift_py_tests.floor import StringValue

    term = reduce_term(
        "container.__getitem__(i)",
        binds={
            "container": StringValue("ABCD"),
            "i": SymbolicValue(make_var("i")),
        },
    )
    assert term.name == "py.subscript", (
        f"5762 call:__getitem__: expected recognized ctor `py.subscript`, "
        f"got `{term.name}` (opaque call: coordinate == still unclassified)"
    )


# ---------------------------------------------------------------------------
# Reflected: `x.__rfloordiv__(y)` means `y // x`, not `x // y` -- the operand
# order is the teeth. #5663 (11 rows) is entirely this shape.
# ---------------------------------------------------------------------------


def test_reflected_rfloordiv_dunder_call_swaps_operand_order() -> None:
    # (2).__rfloordiv__(7) means 7 // 2 == 3, NOT 2 // 7 == 0.
    assert reduce_value("(2).__rfloordiv__(7)").value == 3
    assert reduce_value("(2).__rfloordiv__(7)").value != reduce_value(
        "(2).__floordiv__(7)"
    ).value


def test_reflected_radd_dunder_call_matches_commutative_operator() -> None:
    assert reduce_value("(2).__radd__(7)").value == reduce_value("7 + 2").value


# ---------------------------------------------------------------------------
# Lying twins that MUST refute.
# ---------------------------------------------------------------------------


def test_same_named_non_dunder_method_is_not_bridged() -> None:
    """A lookalike method that merely SHARES a name-shaped string with a
    dunder (but isn't one) never authenticates: only exact dunder spellings
    in the closed operator vocabulary own the Call."""
    node = ast.parse("x.mul(3)", mode="eval").body
    from sugar_lift_py_tests.factory.source_fragment import SourceFragment

    site = SourceFragment.from_node(node, "t.py")
    assert DunderOperatorCallSugar.owns(site) is False


def test_getattr_indirected_dunder_is_not_bridged() -> None:
    """``getattr(x, '__mul__')(y)`` reaches the same runtime method but is
    NOT the ``receiver.__dunder__`` Attribute Call shape -- the callee is a
    Call (``getattr(...)``), not an Attribute, so this never authenticates
    structurally and must refute the bridge."""
    node = ast.parse("getattr(x, '__mul__')(3)", mode="eval").body
    from sugar_lift_py_tests.factory.source_fragment import SourceFragment

    site = SourceFragment.from_node(node, "t.py")
    assert DunderOperatorCallSugar.owns(site) is False


def test_wrong_arity_dunder_call_is_not_bridged() -> None:
    """``x.__mul__(y, z)`` (extra positional) or ``x.__mul__()`` (missing
    operand) is not the operator's own arity and must refute."""
    from sugar_lift_py_tests.factory.source_fragment import SourceFragment

    for expr in ("x.__mul__(3, 4)", "x.__mul__()"):
        node = ast.parse(expr, mode="eval").body
        site = SourceFragment.from_node(node, "t.py")
        assert DunderOperatorCallSugar.owns(site) is False


def test_keyword_dunder_call_is_not_bridged() -> None:
    """``x.__mul__(other=y)`` is spelled with a keyword, not the operator's
    positional-only shape, and must refute the bridge."""
    from sugar_lift_py_tests.factory.source_fragment import SourceFragment

    node = ast.parse("x.__mul__(other=3)", mode="eval").body
    site = SourceFragment.from_node(node, "t.py")
    assert DunderOperatorCallSugar.owns(site) is False


def test_non_numeric_operand_stays_loud_factory_panic() -> None:
    """A shadowed/wrong-type operand hits the SAME typed floor gap the
    operator spelling already raises for ``x * y`` -- the bridge invents no
    new suppression."""
    with pytest.raises(FactoryPanic):
        reduce_value('"a".__mul__("b")')


# ---------------------------------------------------------------------------
# Real-solver truthful/lying twins (end-to-end sat/unsat), mirroring the
# BinOp-family convention in test_binop_sugar.py.
# ---------------------------------------------------------------------------


def test_explicit_mul_dunder_call_truthful_and_lying_twins_refute(tmp_path) -> None:
    truthful = run_source_through_real_solver(
        tmp_path / "truthful",
        "def A():\n    return (5).__mul__(3)\n\n"
        "def test_a():\n    assert A() == 15\n",
    )
    lying = run_source_through_real_solver(
        tmp_path / "lying",
        "def A():\n    return (5).__mul__(3)\n\n"
        "def test_a():\n    assert A() == 16\n",
    )
    assert truthful.verdict == "sat"
    assert lying.verdict == "unsat"
    assert "DunderOperatorCallSugar" in truthful.selected_sugars
    assert "DunderOperatorCallSugar" in lying.selected_sugars


def test_explicit_rfloordiv_dunder_call_truthful_and_lying_twins_refute(
    tmp_path,
) -> None:
    truthful = run_source_through_real_solver(
        tmp_path / "truthful",
        "def A():\n    return (2).__rfloordiv__(7)\n\n"
        "def test_a():\n    assert A() == 3\n",
    )
    # The lying twin gets the reflected operand order backwards (2 // 7 == 0).
    lying = run_source_through_real_solver(
        tmp_path / "lying",
        "def A():\n    return (2).__rfloordiv__(7)\n\n"
        "def test_a():\n    assert A() == 0\n",
    )
    assert truthful.verdict == "sat"
    assert lying.verdict == "unsat"
    assert "DunderOperatorCallSugar" in truthful.selected_sugars
    assert "DunderOperatorCallSugar" in lying.selected_sugars
