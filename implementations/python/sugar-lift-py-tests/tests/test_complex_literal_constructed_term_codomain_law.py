"""L2b — ComplexLiteral + sibling leaves are ConstructedTermSugar; one door.

Pink lesson: product promotion already exists (ComplexLiteralSugar /
EllipsisLiteralSugar / Int/Real/String/Bytes/None/bool leaves already carry
ConstructedTermSugar + to_term; Constant construction mints them; BinOpSugar
and Subscript already accept them via require_constructed_term_sugar).

This file pins the law so the codomain cannot silently regress. ONE door —
require_constructed_term_sugar — not patches at BinOpSugar.right alone.
"""

from __future__ import annotations

import hashlib

from sugar_lift_py_tests.sugar.binop_sugar import BinOpSugar
from sugar_lift_py_tests.sugar.bytes_literal_sugar import BytesLiteralSugar
from sugar_lift_py_tests.sugar.complex_literal_sugar import ComplexLiteralSugar
from sugar_lift_py_tests.sugar.ellipsis_literal_sugar import EllipsisLiteralSugar
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.int_literal_sugar import IntLiteralSugar
from sugar_lift_py_tests.sugar.none_literal_sugar import NoneLiteralSugar
from sugar_lift_py_tests.sugar.real_literal_sugar import RealLiteralSugar
from sugar_lift_py_tests.sugar.string_literal_sugar import StringLiteralSugar
from sugar_lift_py_tests.sugar.sugar_base import (
    ConstructedTermSugar,
    require_constructed_term_sugar,
)
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
from sugar_lift_py_tests.sugar.unary_op_sugar import UnaryOpSugar
from sugar_source_tree.nodes import BinOp, Constant, Subscript
from sugar_source_tree.tree import SourceFile
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1

_LITERAL_CLASSES = (
    ComplexLiteralSugar,
    EllipsisLiteralSugar,
    IntLiteralSugar,
    RealLiteralSugar,
    StringLiteralSugar,
    BytesLiteralSugar,
    NoneLiteralSugar,
    TrueBoolLiteralSugar,
    FalseBoolLiteralSugar,
)

_OWNERS = (
    "BinOpSugar.left",
    "BinOpSugar.right",
    "UnaryOpSugar.operand",
    "EqualityOpSugar.left",
    "EqualityOpSugar.right",
    "CallSiteSugar.args",
    "CallSiteSugar.keywords",
    "MethodCallSugar.args",
    "MethodCallSugar.keywords",
    "MethodCallSugar.receiver",
    "IfExpSugar.body",
    "IfExpSugar.orelse",
)


class _Site:
    def seal(self):
        return type(
            "S",
            (),
            {
                "source_cid": "blake3-512:" + "0" * 128,
                "start": 0,
                "end": 1,
                "cid": "blake3-512:" + "1" * 128,
            },
        )()


def _cid(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _sf(source: str, name: str = "t.py") -> SourceFile:
    return SourceFile(
        (source, name, _cid(source)),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )


def test_all_literal_leaves_are_constructed_term_sugar() -> None:
    for cls in _LITERAL_CLASSES:
        assert issubclass(cls, ConstructedTermSugar), cls.__name__


def test_one_codomain_door_accepts_complex_and_ellipsis() -> None:
    site = _Site()
    complex_lit = ComplexLiteralSugar(real=0.0, imag=2.0, site=site)
    ellipsis_lit = EllipsisLiteralSugar(site=site)
    for owner in _OWNERS:
        assert require_constructed_term_sugar(complex_lit, owner=owner) is complex_lit
        assert require_constructed_term_sugar(ellipsis_lit, owner=owner) is ellipsis_lit


def test_binop_slot_constructs_with_complex_literal() -> None:
    """BinOpSugar.right is the historical rejection site — door admits, no patch."""
    site = _Site()
    left = IntLiteralSugar(value=1, site=site)
    right = ComplexLiteralSugar(real=0.0, imag=2.0, site=site)
    sugar = BinOpSugar(op_kind="Add", left=left, right=right, site=site)
    assert isinstance(sugar.right, ComplexLiteralSugar)
    assert isinstance(sugar.right, ConstructedTermSugar)
    sugar.right.to_term(owner="l2b_binop_complex")
    sugar.to_term(owner="l2b_binop")


def test_unary_slot_constructs_with_complex_literal() -> None:
    site = _Site()
    operand = ComplexLiteralSugar(real=0.0, imag=1.0, site=site)
    sugar = UnaryOpSugar(op_kind="USub", operand=operand, site=site)
    assert isinstance(sugar.operand, ComplexLiteralSugar)
    sugar.operand.to_term(owner="l2b_unary_complex")


def test_production_binop_complex_and_subscript_ellipsis() -> None:
    """Tree construction: already reachable — pin so regression panics."""
    src = "def g():\n    return 1 + 2j\n"
    sf = _sf(src, "complex_binop_l2b.py")
    binop = next(n for n in sf.root.walk() if isinstance(n, BinOp))
    sugar = binop.sugar()
    assert isinstance(sugar, ConstructedTermSugar)
    assert isinstance(sugar.right, ComplexLiteralSugar)
    sugar.right.to_term(owner="l2b_prod_complex")

    src2 = "def g(x):\n    return x[..., :]\n"
    sf2 = _sf(src2, "ellipsis_sub_l2b.py")
    sub = next(n for n in sf2.root.walk() if isinstance(n, Subscript))
    sub_sugar = sub.sugar()
    assert isinstance(sub_sugar, ConstructedTermSugar)
    sub_sugar.to_term(owner="l2b_prod_ellipsis")


def test_sibling_literals_construct_from_constant() -> None:
    """Whole leaf codomain once — not only Complex."""
    cases = (
        ("1", IntLiteralSugar),
        ("1.5", RealLiteralSugar),
        ("'a'", StringLiteralSugar),
        ("b'x'", BytesLiteralSugar),
        ("None", NoneLiteralSugar),
        ("True", TrueBoolLiteralSugar),
        ("False", FalseBoolLiteralSugar),
        ("...", EllipsisLiteralSugar),
        ("2j", ComplexLiteralSugar),
    )
    for src, cls in cases:
        full = f"x = {src}\n"
        sf = _sf(full, f"{cls.__name__}.py")
        const = next(n for n in sf.root.walk() if isinstance(n, Constant))
        sugar = const.sugar()
        assert isinstance(sugar, cls), (src, type(sugar).__name__)
        assert isinstance(sugar, ConstructedTermSugar)
        sugar.to_term(owner=f"l2b_{cls.__name__}")
