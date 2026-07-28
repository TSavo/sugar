"""Canonical construction testimony for ``EqualityOpSugar``."""

from dataclasses import dataclass

import pytest

from sugar_lift_py_tests.ir import str_const
from sugar_lift_py_tests.sugar.equality_op_sugar import EqualityOpSugar
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


@dataclass(frozen=True)
class _TamperedOperand(ConstructedTermSugar):
    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):  # pragma: no cover - term-only fixture
        raise AssertionError("term projection must not execute operands")


@dataclass(frozen=True)
class _Coordinate:
    cid: str


def _sites(source="left == right\n"):
    tree = SourceFile((source, "equality.py", blake3_512_of(source.encode())))
    return tuple(node.fragment for node in tree.nodes() if node.kind == "Compare")


def _equality(left="left", right="right", site=None, coordinate="a"):
    if site is None:
        site = _sites()[0]
    return EqualityOpSugar(
        _Operand(left),
        _Operand(right),
        site,
        left_coordinate=_Coordinate("blake3-512:" + coordinate * 128),
    )


def test_identical_equality_preimages_yield_identical_terms():
    assert _equality(site=_sites()[0]).to_term(owner="first") == _equality(
        site=_sites()[0]
    ).to_term(owner="second")


def test_changed_equality_occurrence_changes_term():
    first, second = _sites("left == right\nleft == right\n")
    assert _equality(site=first).to_term(owner="first") != _equality(
        site=second
    ).to_term(owner="second")


@pytest.mark.parametrize(
    "variant",
    (
        _equality("right", "left"),
        _equality("left", "changed"),
        _equality(coordinate="b"),
    ),
    ids=("operand-order", "operand-testimony", "refinement-coordinate"),
)
def test_changed_equality_preimage_changes_term(variant):
    assert _equality().to_term(owner="baseline") != variant.to_term(owner="variant")


def test_tampered_equality_operand_refuses_term_projection():
    with pytest.raises(TypeError, match="abstract method 'to_term'"):
        _TamperedOperand()
