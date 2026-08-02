"""A chained Compare evaluates each source operand exactly once."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Compare
from sugar_source_tree.tree import SourceFile


@dataclass(frozen=True)
class _CountingMiddleSugar(ConstructedTermSugar):
    inner: ConstructedTermSugar
    evaluations: list[int] = field(compare=False)

    @property
    def site(self):
        return self.inner.site

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        self.evaluations.append(len(self.evaluations) + 1)
        return self.inner.desugar(ctx)

    def to_term(self, *, owner: str):
        return self.inner.to_term(owner=owner)


@dataclass(frozen=True)
class _ChangingMiddleSugar(ConstructedTermSugar):
    inner: ConstructedTermSugar
    evaluations: list[int] = field(compare=False)

    @property
    def site(self):
        return self.inner.site

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        del ctx
        observed = len(self.evaluations) + 1
        self.evaluations.append(observed)
        return Complete(TermValue(observed))

    def to_term(self, *, owner: str):
        return self.inner.to_term(owner=owner)


def _production_chain(middle_type):
    source = "result = 0 < 1 < 2\n"
    tree = SourceFile(
        (source, "chained-compare-once.py", blake3_512_of(source.encode()))
    )
    compare = next(node for node in tree.nodes() if isinstance(node, Compare))
    chain = compare.sugar()
    assert len(chain.values) == 2
    assert chain.values[0].right is chain.values[1].left

    evaluations: list[int] = []
    middle = middle_type(chain.values[0].right, evaluations)
    first = replace(chain.values[0], right=middle)
    second = replace(chain.values[1], left=middle)
    return replace(chain, values=(first, second)), evaluations


def test_chained_compare_desugars_middle_operand_exactly_once() -> None:
    chain, evaluations = _production_chain(_CountingMiddleSugar)

    outcome = chain.desugar(None)

    assert isinstance(outcome, Complete)
    assert evaluations == [1]


def test_second_middle_evaluation_would_change_the_comparison_result() -> None:
    chain, _evaluations = _production_chain(_ChangingMiddleSugar)

    outcome = chain.desugar(None)

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, TrueBoolLiteralSugar)
