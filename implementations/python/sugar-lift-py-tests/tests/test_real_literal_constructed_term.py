"""Real literals carry exact, source-authenticated construction testimony."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.ir import PrimitiveSort
from sugar_lift_py_tests.no_call_body_attribution import _exceptional_exit_effects
from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.int_literal_sugar import IntLiteralSugar
from sugar_lift_py_tests.sugar.real_literal_sugar import RealLiteralSugar
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar, Sugar
from sugar_lift_py_tests.sugar.unary_op_sugar import UnaryOpSugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Constant, UnaryOp
from sugar_source_tree.tree import SourceFile


def _unary(source: str, name: str) -> UnaryOp:
    tree = SourceFile((source, name, blake3_512_of(source.encode())))
    return next(node for node in tree.nodes() if isinstance(node, UnaryOp))


def test_real_literal_admits_truthful_renamed_and_contextual_unary_sources() -> None:
    direct = _unary("~3.5\n", "direct.py")
    renamed = _unary("def renamed():\n    return ~3.5\n", "renamed.py")

    for node in (direct, renamed):
        literal = node.operand.sugar()
        assert isinstance(literal, RealLiteralSugar)
        assert isinstance(literal, ConstructedTermSugar)
        outcome = node.sugar().desugar(None)
        effects = _exceptional_exit_effects(outcome)
        assert len(effects) == 1
        assert effects[0].exception_name == "TypeError"


def test_real_literal_term_seals_value_sort_and_exact_occurrence() -> None:
    first = _unary("~3.5\n", "first.py").operand.sugar()
    second = _unary("\n~3.5\n", "second.py").operand.sugar()
    integer_node = next(
        node
        for node in SourceFile(("~3\n", "integer.py", blake3_512_of(b"~3\n"))).nodes()
        if isinstance(node, Constant)
    )
    integer = integer_node.sugar()

    first_term = first.to_term(owner="real-first")
    assert first_term.args[1].sort == PrimitiveSort("Real")
    assert first_term != second.to_term(owner="real-second")
    assert first_term != integer.to_term(owner="integer-sort-twin")


def test_real_literal_term_names_its_value_as_its_term_value_does() -> None:
    """One name per float: the canonical decimal, never the float's repr.

    ``repr(1e-07)`` is ``'1e-07'``; the TermValue the literal desugars to names
    the same value ``0.0000001``.  The construction term carries that one.
    """
    literal = _unary("~1e-07\n", "exponent.py").operand.sugar()
    assert isinstance(literal, RealLiteralSugar)
    value_term = literal.to_term(owner="real-exponent").args[1]
    assert value_term == TermValue(1e-07).to_term(owner="real-exponent")
    assert value_term.value == "0.0000001"
    assert value_term.value != repr(1e-07)


@dataclass(frozen=True)
class _PrivateOperand(Sugar):
    site: object

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        del ctx
        return ExitSet.completed(TermValue(3.5))


def test_private_operand_cannot_claim_real_literal_construction() -> None:
    node = _unary("~3.5\n", "private.py")
    with pytest.raises(TypeError, match="requires ConstructedTermSugar"):
        UnaryOpSugar("Invert", _PrivateOperand(node.operand.fragment), node.fragment)
