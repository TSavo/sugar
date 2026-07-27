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
from sugar_lift_py_tests.floor import RaiseValue, SymbolicValue, TermValue
from sugar_lift_py_tests.ir import atomic, make_var, not_
from sugar_lift_py_tests.outcome import Complete, ExitSet, Halted
from sugar_lift_py_tests.outcome.exit_set import false_guard, true_guard
from sugar_lift_py_tests.sugar.bool_op_sugar import BoolOpSugar
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.name_sugar import NameSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
from sugar_lift_py_tests.temporal import TemporalContext
from sugar_lift_py_tests.context import ReduceContext
from sugar_source_tree.panic import SugarNotWritten

CORPUS = authenticated_pandas_corpus().root
UNARY_SITE = CORPUS / "tests/extension/base/ops.py"
BOOLOP_SITE = CORPUS / "tests/generic/test_generic.py"
DEMAND_TABLE_KEY = (
    "blake3-512:0ce7c645a7525f1fe5189b808162b49d3fc3ba3d898bfb3d5086e0f295b8b8d"
    "263fe7f530a6aa34adb125615a21e69fdee249e0314bf199b8f43580375153ab0"
)
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


def test_shared_table_authenticates_unary_and_complete_boolop_family(tmp_path) -> None:
    root = Path(__file__).resolve().parents[4]
    output = tmp_path / "python-demand-table.json"
    pulled = subprocess.run(
        [
            str(root / "bin/sugarbin"),
            "artifact",
            "pull",
            "--kind",
            "python-demand-table",
            "--content-key",
            DEMAND_TABLE_KEY,
            "--output",
            str(output),
            "--runtime",
            "cpython-3.12.13",
        ],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert pulled.returncode == 0, pulled.stderr
    table = json.loads(output.read_text(encoding="utf-8"))
    assert table["contentKey"] == DEMAND_TABLE_KEY
    assert table["authentication"]["python"] == "cpython-3.12.13"
    assert table["authentication"]["authenticatedCorpusManifestCid"] == MANIFEST_CID
    assert table["authentication"]["pandas"] == "3.0.3"
    assert table["identity"]["fileCount"] == 1421
    sites = {
        (row["useSite"]["sourceCid"], row["useSite"]["startLine"])
        for row in table["rows"]
        if row.get("kind") == "context-manager-demand"
        and row.get("gapKind") is None
        and row.get("targetSymbol") == "pytest.raises"
    }
    assert (UNARY_SOURCE_CID, 257) in sites
    assert {(BOOLOP_SOURCE_CID, 151), (BOOLOP_SOURCE_CID, 153)} <= sites


@pytest.mark.parametrize(
    ("method", "operator"),
    (
        ("bitwise_invert", "~"),
        ("unary_minus", "-"),
        ("unary_plus", "+"),
    ),
)
def test_undecided_unary_operand_is_named_refusal(method: str, operator: str) -> None:
    """Success versus TypeError is undecidable without the operand's runtime type."""
    with pytest.raises(SugarNotWritten) as caught:
        getattr(SymbolicValue(make_var("ser")), method)(_Site())

    refusal = caught.value
    assert refusal.owner == "unary_operation_exception_floor"
    assert refusal.observed == f"SymbolicValue {operator}"
    assert "authenticated exceptional exit" in refusal.requested
    assert "TypeError" not in str(refusal)


def test_unary_invert_concrete_integer_truthful_twin_folds() -> None:
    outcome = TermValue(3).bitwise_invert(_Site())
    assert outcome == Complete(TermValue(-4))


def test_unary_invert_concrete_bool_truthful_twin_folds() -> None:
    outcome = TermValue(True).bitwise_invert(_Site())
    assert outcome == Complete(TermValue(-2))


def test_unary_invert_concrete_float_lying_twin_has_typed_effect() -> None:
    outcome = TermValue(3.5).bitwise_invert(_Site())
    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, RaiseValue)
    assert outcome.value.effect.exception_name == "TypeError"


def test_unary_minus_concrete_integer_truthful_twin_folds() -> None:
    outcome = TermValue(5).unary_minus(_Site())
    assert outcome == Complete(TermValue(-5))


def test_unary_plus_concrete_integer_truthful_twin_folds() -> None:
    outcome = TermValue(5).unary_plus(_Site())
    assert outcome == Complete(TermValue(5))


def test_undecided_not_operand_refuses_invented_truth() -> None:
    """``not obj`` cannot invent ``py.truthy`` when ``bool(obj)`` is undecided."""
    from sugar_lift_py_tests.sugar.unary_op_sugar import UnaryOpSugar

    with pytest.raises(SugarNotWritten) as caught:
        UnaryOpSugar("Not", NameSugar("obj1", _Site()), _Site()).desugar(None)

    refusal = caught.value
    assert refusal.owner == "unary_operation_exception_floor"
    assert refusal.observed == "SymbolicValue not"
    assert "authenticated exceptional exit" in refusal.requested
    assert "TypeError" not in str(refusal)
    assert "ValueError" not in str(refusal)


class _EffectSugar:
    def __init__(self, effect):
        self.effect = effect

    def desugar(self, ctx=None):
        from sugar_lift_py_tests.outcome import Incomplete

        return Incomplete(self.effect)


def _boolop(kind: str, left, right, *, temporal=None):
    return BoolOpSugar(kind, (left, right), _Site()).desugar(
        ReduceContext(temporal or TemporalContext.empty())
    )


def test_and_false_short_circuits_rhs_effect_truthful_twin() -> None:
    result = _boolop(
        "And",
        FalseBoolLiteralSugar(_Site()),
        _EffectSugar(ExpectationNotMetEffect("rhs")),
    )
    assert result == Complete(result.value)
    assert result.value.formula == false_guard()


def test_or_true_short_circuits_rhs_effect_truthful_twin() -> None:
    result = _boolop(
        "Or",
        TrueBoolLiteralSugar(_Site()),
        _EffectSugar(ExpectationNotMetEffect("rhs")),
    )
    assert result == Complete(result.value)
    assert result.value.formula == true_guard()


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
    from sugar_lift_py_tests.sugar.sugar_base import Sugar

    positive = atomic("py.gt", [make_var("left"), make_var("zero")])

    @dataclass(frozen=True)
    class _PredicateSugar(Sugar):
        @classmethod
        def witnesses(cls):
            return ()

        def desugar(self, ctx=None):
            del ctx
            return Complete(PredicateValue(positive, "left"))

    outcome = _boolop(
        kind,
        _PredicateSugar(),
        _EffectSugar(ExpectationNotMetEffect("rhs")),
    )

    assert isinstance(outcome, ExitSet)
    halted = [edge for edge in outcome.exits if isinstance(edge, Halted)]
    assert len(halted) == 1
    assert halted[0].guard == rhs_guard


@pytest.mark.parametrize("kind", ("And", "Or"))
def test_undecided_operand_type_refuses_invented_truth(kind: str) -> None:
    """``obj and obj`` cannot invent ``py.truthy`` when ``bool(obj)`` is undecided."""
    with pytest.raises(SugarNotWritten) as caught:
        _boolop(kind, NameSugar("obj1", _Site()), NameSugar("obj2", _Site()))

    refusal = caught.value
    assert refusal.owner == "boolean_operation_exception_floor"
    assert refusal.observed == f"SymbolicValue {'and' if kind == 'And' else 'or'}"
    assert "authenticated exceptional exit" in refusal.requested
    assert "TypeError" not in str(refusal)
    assert "ValueError" not in str(refusal)


def test_pandas_series_boolop_sites_stay_source_undecided() -> None:
    """Truthful pandas ``obj1 and/or obj2`` raise at runtime; producer refuses.

    Site: ``pandas/tests/generic/test_generic.py`` lines 152/154 under
    ``pytest.raises(ValueError)``.  Source does not state Series type at the
    BoolOp, so the producer cannot mint ValueError — only the named refusal.
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

    tree = SourceFile(
        (source, str(path), source_cid),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    for line, operator in ((152, "and"), (154, "or")):
        matches = tuple(
            node
            for node in tree.nodes()
            if isinstance(node, BoolOp) and node.line_col_span().start_line == line
        )
        assert len(matches) == 1
        with pytest.raises(SugarNotWritten) as raised:
            matches[0].sugar().desugar(None)
        refusal = raised.value
        assert refusal.owner == "boolean_operation_exception_floor"
        assert refusal.observed == f"SymbolicValue {operator}"
        assert "authenticated exceptional exit" in refusal.requested
        assert "ValueError" not in str(refusal)


def test_pandas_unary_sites_stay_source_undecided() -> None:
    """Truthful pandas unary raises at runtime; producer refuses without inventing.

    Sites under authenticated pandas 3.0.3:
    - ``tests/extension/base/ops.py`` ``~ser`` / ``~data`` (TypeError)
    - ``tests/frame/test_unary.py`` ``-df`` / ``+df`` (TypeError)
    - ``tests/generic/test_generic.py`` ``not obj1`` (ValueError)
    - ``tests/scalar/test_na_scalar.py`` ``not NA`` (TypeError)
    Source does not state the operand runtime type at the UnaryOp, so the
    producer cannot mint the exception identity — only the named refusal.
    """
    from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
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
        with pytest.raises(SugarNotWritten) as raised:
            matches[0].sugar().desugar(None)
        refusal = raised.value
        assert refusal.owner == "unary_operation_exception_floor", (
            rel,
            line,
            refusal.owner,
        )
        assert refusal.observed == f"SymbolicValue {operator}", (
            rel,
            line,
            refusal.observed,
        )
        assert "authenticated exceptional exit" in refusal.requested
        assert "TypeError" not in str(refusal)
        assert "ValueError" not in str(refusal)
