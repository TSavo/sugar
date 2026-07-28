"""Canonical construction testimony for ``BoolOpSugar``."""

from dataclasses import dataclass

import pytest

from sugar_lift_py_tests.ir import str_const
from sugar_lift_py_tests.sugar.bool_op_sugar import BoolOpSugar
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.tree import SourceFile


@dataclass(frozen=True)
class _Operand(ConstructedTermSugar):
    testimony: str

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):  # pragma: no cover - term-only fixture
        raise AssertionError("term projection must not execute operands")

    def to_term(self, *, owner: str):
        del owner
        return str_const(self.testimony)


def _sites(source="left and right\n"):
    tree = SourceFile((source, "boolop.py", blake3_512_of(source.encode())))
    return tuple(node.fragment for node in tree.nodes() if node.kind == "BoolOp")


def _boolop(kind="And", values=("left", "right"), site=None):
    if site is None:
        site = _sites()[0]
    return BoolOpSugar(kind, tuple(_Operand(value) for value in values), site)


def test_identical_boolop_preimages_yield_identical_terms():
    assert _boolop(site=_sites()[0]).to_term(owner="first") == _boolop(
        site=_sites()[0]
    ).to_term(owner="second")


def test_changed_boolop_occurrence_changes_term():
    first, second = _sites("left and right\nleft and right\n")
    assert _boolop(site=first).to_term(owner="first") != _boolop(
        site=second
    ).to_term(owner="second")


@pytest.mark.parametrize(
    "variant",
    (
        _boolop(kind="Or"),
        _boolop(values=("right", "left")),
        _boolop(values=("left", "changed")),
    ),
    ids=("operator", "operand-order", "operand-testimony"),
)
def test_changed_boolop_preimage_changes_term(variant):
    assert _boolop().to_term(owner="baseline") != variant.to_term(owner="variant")


def test_tampered_boolop_operator_refuses_term_projection():
    with pytest.raises(ValueError, match="authenticated BoolOp operator"):
        _boolop(kind="Xor").to_term(owner="tampered")
