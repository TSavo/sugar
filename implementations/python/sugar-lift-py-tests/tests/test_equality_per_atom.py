"""#4371 — ADJUDICATED equality vocabulary (T, 2026-07-13).

Neither ``=`` nor ``py.eq`` is the global vocabulary. Equality resolves PER
ATOM at construction, by sort warrant:

1. Same sort with warrant (Int/Int, Real/Real, Bool/Bool, String/String,
   literal ground cases): emit FOL ``=`` directly. py.eq and = coincide;
   = is exact, no loss.
2. Mismatched numeric sorts (Int vs Real): ``=`` is ILL-SORTED in the
   many-sorted calculus — not false, not-even-a-formula. Python's
   cross-tower ``1 == 1.0`` is real semantics. Emit ``py.eq(x, y)`` and
   discharge through the EXPLICIT promotion bridge
   ``py.eq(x, y) -> to_real(x) = y``. There is deliberately NO Number
   supersort; the bridge does the supersort's job without collapsing the
   tower.
3. Unknown/opaque sort or overridable ``__eq__``: ``py.eq`` is the stated
   fact; it discharges to ``=`` only under a sort warrant, otherwise it
   stands as the honest constructor.

Rationale: FOL ``=`` is a predicate about denotation and never runs;
Python ``==`` is a computation. They coincide exactly when the sorts prove
they do — the type is the resolution, decided once at atom construction,
never a global flag.

Door: ``resolve_equality_atom`` (via ``FloorValue.equals`` and every chain
pair in ``ChainedCompareSugar``). Typed ProofIR ``Eq`` rejects mixed
numeric sorts without an explicit promotion term. Residual R=0 when every
construction path is through that door and the three arms discriminate.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory import FactoryPanic
from sugar_lift_py_tests.floor import (
    OpaqueOpCallsite,
    PredicateValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.ir import eq, make_var, py_eq
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.proofir.formulas import Eq
from sugar_lift_py_tests.proofir.sorts import IntSort, RealSort
from sugar_lift_py_tests.proofir.terms import ConstTerm


def _equality(left, right) -> PredicateValue:
    value = complete_value(left.equals(right, "assertion"), owner="test equality")
    assert isinstance(value, PredicateValue)
    return value


def test_same_sort_int_warrant_emits_fol_equality_only() -> None:
    call = OpaqueOpCallsite("len", TermValue(7), computed=TermValue(1))

    predicate = _equality(call, TermValue(1))

    assert predicate.formula == eq(
        call.to_term(owner="test"), TermValue(1).to_term(owner="test")
    )
    assert predicate.formula != py_eq(
        call.to_term(owner="test"), TermValue(1).to_term(owner="test")
    )


def test_same_sort_real_warrant_emits_fol_equality_only() -> None:
    call = OpaqueOpCallsite("scale", TermValue(0.0), computed=TermValue(1.5))

    predicate = _equality(call, TermValue(2.5))

    assert predicate.formula == eq(
        call.to_term(owner="test"), TermValue(2.5).to_term(owner="test")
    )
    assert predicate.formula.name == "="


def test_mixed_int_real_warrant_emits_py_eq_and_explicit_promotion_bridge() -> None:
    call = OpaqueOpCallsite("len", TermValue(7), computed=TermValue(1))

    predicate = _equality(call, TermValue(1.5))

    assert predicate.formula == py_eq(
        call.to_term(owner="test"), TermValue(1.5).to_term(owner="test")
    )
    assert predicate.formula != eq(
        call.to_term(owner="test"), TermValue(1.5).to_term(owner="test")
    )
    assert len(predicate.derived_formulas) == 2
    promotion = predicate.derived_formulas[1]
    assert promotion.kind == "implies"
    assert promotion.operands[0] == predicate.formula
    promoted_eq = promotion.operands[1]
    assert promoted_eq.name == "="
    assert promoted_eq.args[0].name == "to_real"


def test_mixed_real_int_order_still_bridges_without_bare_eq() -> None:
    """Ill-sorted bare ``=`` is forbidden regardless of operand order."""
    call = OpaqueOpCallsite("len", TermValue(7), computed=TermValue(1))

    predicate = _equality(TermValue(1.5), call)

    assert predicate.formula.name == "py.eq"
    assert predicate.formula != eq(
        TermValue(1.5).to_term(owner="test"), call.to_term(owner="test")
    )
    assert any(
        getattr(bridge, "kind", None) == "implies"
        and getattr(bridge.operands[1], "name", None) == "="
        and getattr(bridge.operands[1].args[0], "name", None) == "to_real"
        for bridge in predicate.derived_formulas
    )


def test_opaque_equality_stays_py_eq_without_sort_bridge() -> None:
    opaque = SymbolicValue(make_var("opaque"))

    predicate = _equality(opaque, TermValue(1))

    assert predicate.formula == py_eq(
        make_var("opaque"), TermValue(1).to_term(owner="test")
    )
    assert predicate.derived_formulas == ()


def test_typed_eq_rejects_mixed_numeric_sorts_without_explicit_promotion() -> None:
    with pytest.raises(FactoryPanic, match="matching sorts for Eq"):
        Eq(ConstTerm(1, sort=IntSort()), ConstTerm("1.0", sort=RealSort()))


def test_chained_eq_uses_per_atom_resolution_not_hardcoded_py_eq() -> None:
    """ChainedCompareSugar must not bypass resolve_equality_atom (#4371 residual)."""
    from sugar_lift_py_tests.sugar.chained_compare_sugar import _guarded_op_atom

    call = OpaqueOpCallsite("len", TermValue(7), computed=TermValue(1))

    same_formula, same_bridges = _guarded_op_atom("Eq", call, TermValue(1), "site")
    assert same_formula.name == "=", same_formula
    assert same_bridges == ()

    mixed_formula, mixed_bridges = _guarded_op_atom("Eq", call, TermValue(1.5), "site")
    assert mixed_formula.name == "py.eq", mixed_formula
    assert len(mixed_bridges) == 1
    assert mixed_bridges[0].kind == "implies"
    assert mixed_bridges[0].operands[1].args[0].name == "to_real"

    opaque = SymbolicValue(make_var("opaque"))
    opaque_formula, opaque_bridges = _guarded_op_atom(
        "Eq", opaque, TermValue(1), "site"
    )
    assert opaque_formula.name == "py.eq", opaque_formula
    assert opaque_bridges == ()

    # Sugar ownership: multi-Eq Compare is ChainedCompareSugar, and each same-sort
    # Int face resolves to FOL ``=`` (not a hardcoded py.eq).
    tree = ast.parse("assert 1 == 1 == 1\n")
    compare = tree.body[0].test
    assert isinstance(compare, ast.Compare) and len(compare.ops) == 2
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    sugar = build_node(compare, filename="t.py", role=SugarRole.TERM, ctx=ctx).sugar
    assert type(sugar).__name__ == "ChainedCompareSugar"
    value = complete_value(sugar.desugar(ctx), owner="chain")
    assert isinstance(value, PredicateValue)
    faces = (
        value.formula.operands
        if getattr(value.formula, "kind", None) == "and"
        else (value.formula,)
    )
    for face in faces:
        assert face.name == "=", (
            f"chained same-sort Int face must resolve to FOL =, got {face}"
        )


def test_equality_construction_door_has_no_chain_hardcode() -> None:
    """Static residual instrument: chain sugar must not hardcode py_eq for Eq.

    Replacement architecture: every Eq/NotEq pair goes through
    ``resolve_equality_atom``. R is the count of non-comment ``py_eq`` tokens
    in the chain helper; stable zero means the door is closed.
    """
    path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "sugar_lift_py_tests"
        / "sugar"
        / "chained_compare_sugar.py"
    )
    offenders: list[str] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        if "py_eq" in line:
            offenders.append(f"{path}:{lineno}: {line.rstrip()}")
    assert offenders == [], (
        f"R(chained_eq_hardcode_py_eq)={len(offenders)}; "
        "each must route through resolve_equality_atom:\n"
        + "\n".join(f"  {row}" for row in offenders)
    )
