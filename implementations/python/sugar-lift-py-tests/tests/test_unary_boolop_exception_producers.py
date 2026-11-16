"""UnaryOp and BoolOp exceptional-exit producer laws.

The corpus witnesses are pandas 3.0.3 source, while the discrimination twins
exercise the native floors directly.  No assertion-manager spelling grants an
operator an exception it cannot establish from source.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
from sugar_lift_py_tests.effect.expectation_not_met_effect import (

    ExpectationNotMetEffect,
)
from sugar_lift_py_tests.floor import SymbolicValue, TermValue
from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.ir import atomic, make_var, not_, str_const
from sugar_lift_py_tests.outcome import ExitSet, Halted
from sugar_lift_py_tests.outcome.exit_set import false_guard, true_guard
from sugar_lift_py_tests.sugar.bool_op_sugar import BoolOpSugar
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.name_sugar import NameSugar
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
from sugar_lift_py_tests.temporal import TemporalContext
from sugar_lift_py_tests.context import ReduceContext

from sugar_lift_py_tests.repo_root import resolve_repo_root
from sugar_lift_python_source.canonical import blake3_512_of

CORPUS = authenticated_pandas_corpus().root
UNARY_SITE = CORPUS / "tests/extension/base/ops.py"
BOOLOP_SITE = CORPUS / "tests/generic/test_generic.py"
MANIFEST_CID = (
    "blake3-512:6f317a5a489eb7e730064d79792f0d1656723130603309e2f2ed9cbedb604eda"
    "1c4b77a26dc90c980411292ea3994af9015da4cd850b5a307af5a4998b563530"
)
UNARY_SOURCE_CID = (
    "blake3-512:e67b3f17a16e69f16ea8d1e0b19eff3f27f8acb8beac1dcb923066ad5901c039"
    "a6949846351444d20ec05e193006125a7781fe4ef2503e0f8eb6bfebffbc7fca"
)
BOOLOP_SOURCE_CID = (
    "blake3-512:851b7839bb2cdb42bcb34227ea39b4c84e8324ca164a5875283b934ede5935cb4"
    "ce94ecaf08a4e83d608f9c9a676760892b1be24f953f9a1999175d479a8075c"
)


class _Site:
    filename = "pandas-producer-twin.py"
    line = 1
    col = 0
    source = "operator"
    unit = type("_Unit", (), {"source": "~value\n"})()


class _FragmentSite(_Site):
    """``_Site`` with a source fragment's coordinate: an undecided truth's
    faces key their atom on the operation's occurrence
    (``occurrence.occurrence_key``), and a site with no source coordinate is
    refused by name (#7808)."""

    class _Span:
        start_line, start_col, end_line, end_col = 1, 0, 1, 8

    source_cid = blake3_512_of(b"operator")
    line_col_span = _Span()


def test_verified_pandas_303_reproducers_are_content_pinned() -> None:
    assert hashlib.sha256(UNARY_SITE.read_bytes()).hexdigest() == (
        "bd98339ca8660c94faf9afdd8900d382a27c88c7f179a71f2a165b278d2bb66e"
    )
    assert hashlib.sha256(BOOLOP_SITE.read_bytes()).hexdigest() == (
        "cbc5383e8e1545537baedca85a6c62a487d3bea6942bb56e5e0c7479dd2f188d"
    )
    assert (
        "with pytest.raises(TypeError):\n                ~ser" in UNARY_SITE.read_text()
    )
    source = BOOLOP_SITE.read_text()
    assert (
        "with pytest.raises(ValueError, match=msg):\n            obj1 and obj2"
        in source
    )
    assert (
        "with pytest.raises(ValueError, match=msg):\n            obj1 or obj2" in source
    )


@pytest.mark.parametrize(
    ("method", "operator"),
    (
        ("bitwise_invert", "~"),
        ("unary_minus", "-"),
        ("unary_plus", "+"),
    ),
)
def test_undecided_unary_operand_is_the_two_faces(method: str, operator: str) -> None:
    """Success versus TypeError is undecidable without the operand's runtime
    type, formal or not: the one undecided unary's two faces (#7757 NEW-8)."""
    outcome = getattr(SymbolicValue(make_var("ser")), method)(_FragmentSite())

    _assert_two_faced_unary(outcome, method, operator)


def _assert_two_faced_unary(outcome, method: str, operator: str) -> None:
    """``-x`` / ``+x`` / ``~x`` over an operand whose type is undecided: the
    one undecided unary (``FloorValue.undecided_unary``).  It completes only
    under ``python:unary_op.completes`` with the per-evaluation
    ``python:unary_result``; the complement halts with an
    UndeterminedRaiseEffect naming no exception type."""
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.outcome.exit_set import Completed

    assert isinstance(outcome, ExitSet)
    halted = [edge for edge in outcome.exits if isinstance(edge, Halted)]
    assert len(halted) == 1
    assert type(halted[0].effect) is UndeterminedRaiseEffect
    assert halted[0].effect.producer_node_owner == f"SymbolicValue.{method}"
    assert "TypeError" not in repr(halted[0].effect)
    completed = [edge for edge in outcome.exits if isinstance(edge, Completed)]
    assert len(completed) == 1
    assert "python:unary_op.completes" in repr(completed[0].guard)
    assert completed[0].value.term.name == "python:unary_result"
    assert completed[0].value.term.args[0].value == operator


def test_unary_invert_concrete_integer_truthful_twin_folds() -> None:
    outcome = TermValue(3).bitwise_invert(_Site())
    assert outcome == ExitSet.completed(TermValue(-4))


def test_unary_invert_concrete_bool_truthful_twin_folds() -> None:
    outcome = TermValue(True).bitwise_invert(_Site())
    assert outcome == ExitSet.completed(TermValue(-2))


def test_unary_invert_concrete_float_lying_twin_has_typed_effect() -> None:
    outcome = TermValue(3.5).bitwise_invert(_Site())
    assert outcome.halts() == outcome.exits
    (halt,) = outcome.halts()
    assert isinstance(halt.effect, RaiseEffect)
    assert halt.effect.exception_name == "TypeError"


def test_unary_minus_concrete_integer_truthful_twin_folds() -> None:
    outcome = TermValue(5).unary_minus(_Site())
    assert outcome == ExitSet.completed(TermValue(-5))


def test_unary_plus_concrete_integer_truthful_twin_folds() -> None:
    outcome = TermValue(5).unary_plus(_Site())
    assert outcome == ExitSet.completed(TermValue(5))


def _assert_two_faced_not(outcome, operand_term) -> None:
    """``not obj``: undecided ``bool(obj)`` is the one truth rule's two faces.

    The truth completes only under ``python:truth.completes`` over the
    operand's term, and only that completed truth is negated; the complement
    halts with an UndeterminedRaiseEffect naming no exception type.
    """
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.floor.floor_value import undecided_truth_result
    from sugar_lift_py_tests.floor.predicate_value import PredicateValue
    from sugar_lift_py_tests.outcome.exit_set import Completed

    assert isinstance(outcome, ExitSet)
    halted = [edge for edge in outcome.exits if isinstance(edge, Halted)]
    assert len(halted) == 1
    assert type(halted[0].effect) is UndeterminedRaiseEffect
    assert halted[0].effect.producer_node_owner == "UnaryOpSugar.not"
    assert "python:truth.completes" in repr(halted[0].guard)
    assert repr(operand_term) in repr(halted[0].guard)
    assert "TypeError" not in repr(halted[0])
    assert "ValueError" not in repr(halted[0])
    completed = [edge for edge in outcome.exits if isinstance(edge, Completed)]
    assert len(completed) == 1
    assert "python:truth.completes" in repr(completed[0].guard)
    assert isinstance(completed[0].value, PredicateValue)
    # The truth is keyed per evaluation, at the halt's own key (#7757 NEW-1).
    assert completed[0].value.formula == not_(
        undecided_truth_result(operand_term, halted[0].effect.occurrence)
    )


def test_undecided_not_operand_is_the_two_faced_truth() -> None:
    """``not obj`` takes ``bool(obj)`` by the one truth rule, never a refusal.

    No ``py.truthy`` completion is claimed unguarded and no exception
    identity is invented.
    """
    from sugar_lift_py_tests.sugar.unary_op_sugar import UnaryOpSugar

    outcome = UnaryOpSugar(
        "Not", NameSugar("obj1", _Site()), _FragmentSite()
    ).desugar(None)
    _assert_two_faced_not(outcome, make_var("obj1"))


def _undecided_truth_values():
    from sugar_lift_py_tests.floor.manager_coordinate import RaisedExitTypeValue
    from sugar_lift_py_tests.floor.undetermined_exception_value import (
        UndeterminedExceptionTypeValue,
        UndeterminedExceptionValue,
    )
    from sugar_lift_py_tests.ir import ctor, str_const

    raised = UndeterminedExceptionValue("probe:occurrence", "probe:producer")
    return (
        SymbolicValue(make_var("obj1")),
        # A parameter: its truth waits on no caller's actual either
        # (#7757 NEW-1).
        SymbolicValue(make_var("p"), formal_coordinate=object()),
        raised,
        UndeterminedExceptionTypeValue(raised),
        # The class a raise threw, handed to ``__exit__``: its own formal
        # coordinate, so it waits on no caller's actual.
        RaisedExitTypeValue(
            ctor(
                "python:exception_type_identity",
                [str_const("builtins"), str_const("ValueError")],
            )
        ),
    )


@pytest.mark.parametrize(
    "value", _undecided_truth_values(), ids=lambda value: type(value).__name__
)
def test_every_value_whose_truth_is_undecided_is_the_two_faced_truth(value) -> None:
    """``bool(value)`` for a value whose runtime type is not decided is the
    undecided member's two faces, with its own term at its own site -- the
    exception an undetermined raise threw and its type, and the class a raise
    threw, as much as a bare symbolic value.  None of them is refused."""
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.floor.floor_value import undecided_truth_result
    from sugar_lift_py_tests.floor.predicate_value import PredicateValue
    from sugar_lift_py_tests.outcome.exit_set import Completed
    from sugar_lift_py_tests.sugar.bool_op_sugar import truth_of

    outcome = truth_of(value, _FragmentSite(), owner="probe.truth")
    term = value.to_term(owner="probe")
    halted = [edge for edge in outcome.exits if isinstance(edge, Halted)]
    completed = [edge for edge in outcome.exits if isinstance(edge, Completed)]
    assert len(halted) == 1 and len(completed) == 1
    assert type(halted[0].effect) is UndeterminedRaiseEffect
    assert halted[0].effect.producer_node_owner == "probe.truth"
    assert "python:truth.completes" in repr(completed[0].guard)
    assert repr(term) in repr(completed[0].guard)
    assert isinstance(completed[0].value, PredicateValue)
    # The truth is keyed per evaluation, at the halt's own key (#7757 NEW-1).
    assert completed[0].value.formula == undecided_truth_result(
        term, halted[0].effect.occurrence
    )
    assert outcome.owed_items()


def test_a_guarded_value_takes_each_arms_truth_through_the_one_truth_rule() -> None:
    """``bool`` of a guarded value: each arm's truth through the one truth
    rule.  An arm whose truth is not decided keeps its two faces under its
    own polarity, beside the other arm's decided truth."""
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.floor.guarded_value import GuardedValue
    from sugar_lift_py_tests.outcome.exit_set import Completed

    guarded = GuardedValue(
        atomic("probe:guard", []), SymbolicValue(make_var("obj1")), TermValue(1)
    )
    outcome = guarded.truth(_FragmentSite())
    halted = [edge for edge in outcome.exits if isinstance(edge, Halted)]
    completed = [edge for edge in outcome.exits if isinstance(edge, Completed)]
    assert len(halted) == 1
    assert type(halted[0].effect) is UndeterminedRaiseEffect
    assert halted[0].effect.producer_node_owner == "GuardedValue.truth"
    assert "probe:guard" in repr(halted[0].guard)
    assert len(completed) == 2


class _EffectSugar(ConstructedTermSugar):
    """An operand whose evaluation halts.  A BoolOp's operands are constructed
    term sugars (``require_constructed_term_sugar``), so the twin is one."""

    def __init__(self, effect):
        self.effect = effect

    @classmethod
    def witnesses(cls):
        return ()

    def to_term(self, *, owner: str):
        del owner
        return str_const("halting-operand")

    def desugar(self, ctx=None):
        del ctx
        return ExitSet.halted(self.effect)


def _boolop(kind: str, left, right, *, temporal=None, site=None):
    return BoolOpSugar(kind, (left, right), site or _Site()).desugar(
        ReduceContext(temporal or TemporalContext.empty())
    )


def test_and_false_short_circuits_rhs_effect_truthful_twin() -> None:
    result = _boolop(
        "And",
        FalseBoolLiteralSugar(_Site()),
        _EffectSugar(ExpectationNotMetEffect("rhs")),
    )
    assert result == ExitSet.completed(result.completed_value())
    assert isinstance(result.completed_value(), FalseBoolLiteralSugar)


def test_or_true_short_circuits_rhs_effect_truthful_twin() -> None:
    result = _boolop(
        "Or",
        TrueBoolLiteralSugar(_Site()),
        _EffectSugar(ExpectationNotMetEffect("rhs")),
    )
    assert result == ExitSet.completed(result.completed_value())
    assert isinstance(result.completed_value(), TrueBoolLiteralSugar)


@pytest.mark.parametrize(
    ("kind", "rhs_guard"),
    (
        ("And", atomic("py.gt", [make_var("left"), make_var("zero")])),
        ("Or", not_(atomic("py.gt", [make_var("left"), make_var("zero")]))),
    ),
)
def test_predicate_left_makes_rhs_effect_conditional(kind, rhs_guard) -> None:
    """A decided predicate may guard an RHS halt; an undecided *type* may not.

    ``SymbolicValue`` truth is undecided (``bool`` may raise), so inventing
    ``py.truthy`` there is refused.  A source-visible comparison predicate is a
    decided truth formula and still short-circuits its complementary face.
    """
    from dataclasses import dataclass

    from sugar_lift_py_tests.floor.predicate_value import PredicateValue

    positive = atomic("py.gt", [make_var("left"), make_var("zero")])

    @dataclass(frozen=True)
    class _PredicateSugar(ConstructedTermSugar):
        @classmethod
        def witnesses(cls):
            return ()

        def to_term(self, *, owner: str):
            del owner
            return str_const("predicate-operand")

        def desugar(self, ctx=None):
            del ctx
            return ExitSet.completed(PredicateValue(positive, "left"))

    outcome = _boolop(
        kind,
        _PredicateSugar(),
        _EffectSugar(ExpectationNotMetEffect("rhs")),
    )

    assert isinstance(outcome, ExitSet)
    halted = [edge for edge in outcome.exits if isinstance(edge, Halted)]
    assert len(halted) == 1
    assert halted[0].guard == rhs_guard


def _assert_two_faced_symbolic_truth(outcome, left_term, right_term) -> None:
    """``bool(left)`` may complete or raise: both faces, no invented identity.

    The completed faces stand only under ``python:truth.completes`` over the
    left operand's term; the complement halts with an UndeterminedRaiseEffect
    naming no exception type.  One completed face returns the left operand
    (stopping face), the other the right operand (continuing face).
    """
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.outcome.exit_set import Completed

    assert isinstance(outcome, ExitSet)
    halted = [edge for edge in outcome.exits if isinstance(edge, Halted)]
    assert len(halted) == 1
    assert type(halted[0].effect) is UndeterminedRaiseEffect
    assert halted[0].effect.producer_node_owner == "BoolOpSugar.truth"
    assert "python:truth.completes" in repr(halted[0].guard)
    assert repr(left_term) in repr(halted[0].guard)
    assert "TypeError" not in repr(halted[0])
    assert "ValueError" not in repr(halted[0])
    completed = [edge for edge in outcome.exits if isinstance(edge, Completed)]
    returned = {repr(edge.value.to_term(owner="test")) for edge in completed}
    assert returned == {repr(left_term), repr(right_term)}
    for edge in completed:
        assert "python:truth.completes" in repr(edge.guard)


@pytest.mark.parametrize("kind", ("And", "Or"))
def test_undecided_symbolic_operand_truth_is_two_faced(kind: str) -> None:
    """``obj1 or obj2``: undecided ``bool(obj1)`` is two-faced, never total.

    Truthful twin of the #7681 law for a bare symbolic operand: no ``py.truthy``
    completion is claimed unguarded and no exception identity is invented.
    """
    outcome = _boolop(
        kind,
        NameSugar("obj1", _Site()),
        NameSugar("obj2", _Site()),
        site=_FragmentSite(),
    )
    _assert_two_faced_symbolic_truth(outcome, make_var("obj1"), make_var("obj2"))


@pytest.mark.parametrize("kind", ("And", "Or"))
def test_decided_left_operand_adds_no_truth_halt(kind: str) -> None:
    """Lying twin: a decided left operand's truth cannot raise, so no halt."""
    outcome = _boolop(
        kind,
        TrueBoolLiteralSugar(_Site()),
        NameSugar("obj2", _Site()),
    )
    exits = outcome.exits if isinstance(outcome, ExitSet) else ()
    assert not [edge for edge in exits if isinstance(edge, Halted)]
    assert "python:truth.completes" not in repr(outcome)


def test_pandas_series_boolop_sites_stay_source_undecided() -> None:
    """Truthful pandas ``obj1 and/or obj2`` raise at runtime; producer is two-faced.

    Site: ``pandas/tests/generic/test_generic.py`` lines 152/154 under
    ``pytest.raises(ValueError)``.  Source does not state Series type at the
    BoolOp, so the producer cannot mint ValueError: the raise stands only as
    the UndeterminedRaiseEffect face of the #7681 two-faced truth law.
    """
    from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_source_tree.nodes import BoolOp
    from sugar_source_tree.tree import SourceFile

    corpus = authenticated_pandas_corpus()
    assert corpus.manifest_cid == MANIFEST_CID
    path = corpus.root / "tests/generic/test_generic.py"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == (
        "cbc5383e8e1545537baedca85a6c62a487d3bea6942bb56e5e0c7479dd2f188d"
    )
    source = path.read_text(encoding="utf-8")
    source_cid = blake3_512_of(source.encode("utf-8"))
    assert source_cid == BOOLOP_SOURCE_CID

    import pandas

    obj1 = pandas.Series([1, 1, 1, 1])
    obj2 = pandas.Series([1, 1, 1, 1])
    with pytest.raises(ValueError, match="ambiguous"):
        obj1 and obj2
    with pytest.raises(ValueError, match="ambiguous"):
        obj1 or obj2

    construction_context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (source, str(path), source_cid),
        construction_context=construction_context,
    )
    for line, operator in ((152, "and"), (154, "or")):
        matches = tuple(
            node
            for node in tree.nodes()
            if isinstance(node, BoolOp) and node.line_col_span().start_line == line
        )
        assert len(matches) == 1
        del operator
        _assert_two_faced_symbolic_truth(
            matches[0].sugar().desugar(None), make_var("obj1"), make_var("obj2")
        )


def test_pandas_unary_sites_stay_source_undecided() -> None:
    """Truthful pandas unary raises at runtime; producer invents neither face.

    Sites under authenticated pandas 3.0.3:
    - ``tests/extension/base/ops.py`` ``~ser`` / ``~data`` (TypeError)
    - ``tests/frame/test_unary.py`` ``-df`` / ``+df`` (TypeError)
    - ``tests/generic/test_generic.py`` ``not obj1`` (ValueError)
    - ``tests/scalar/test_na_scalar.py`` ``not NA`` (TypeError)
    Source does not state the operand runtime type at the UnaryOp, so the
    producer cannot mint the exception identity.  The arithmetic operators are
    the one undecided unary (#7757 NEW-8); ``not obj1`` and ``not NA`` are the
    one truth rule's two faces; each raise stands only as the
    UndeterminedRaiseEffect face.
    """
    from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_lift_py_tests.ir import ctor
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_source_tree.nodes import UnaryOp
    from sugar_source_tree.tree import SourceFile

    corpus = authenticated_pandas_corpus()
    assert corpus.manifest_cid == MANIFEST_CID

    cases = (
        ("tests/extension/base/ops.py", 258, "~"),
        ("tests/extension/base/ops.py", 260, "~"),
        ("tests/frame/test_unary.py", 56, "-"),
        ("tests/frame/test_unary.py", 133, "+"),
        ("tests/indexes/test_old_base.py", 861, "~"),
        ("tests/scalar/timedelta/test_timedelta.py", 290, "~"),
        ("tests/generic/test_generic.py", 156, "not"),
        ("tests/scalar/test_na_scalar.py", 48, "not"),
    )
    two_faced = {
        ("tests/generic/test_generic.py", 156): make_var("obj1"),
        # ``from pandas._libs.missing import NA`` (line 11 of the file): the
        # import member's closed reference names the import's own target
        # symbol, the module the source states, never a re-export of it.
        ("tests/scalar/test_na_scalar.py", 48): ctor(
            "ref:pandas._libs.missing.NA", [], symbol_kind="coordinate"
        ),
    }
    for rel, line, operator in cases:
        path = corpus.root / rel
        source = path.read_text(encoding="utf-8")
        source_cid = blake3_512_of(source.encode("utf-8"))
        tree = SourceFile(
            (source, str(path), source_cid),
            construction_context=TreeConstructionContextV1.for_source_call_construction(),
        )
        matches = tuple(
            node
            for node in tree.nodes()
            if isinstance(node, UnaryOp) and node.line_col_span().start_line == line
        )
        assert len(matches) == 1, (rel, line, matches)
        if (rel, line) in two_faced:
            _assert_two_faced_not(
                matches[0].sugar().desugar(None), two_faced[(rel, line)]
            )
            continue
        method = {"~": "bitwise_invert", "-": "unary_minus", "+": "unary_plus"}[
            operator
        ]
        _assert_two_faced_unary(matches[0].sugar().desugar(None), method, operator)
