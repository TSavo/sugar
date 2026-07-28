"""Compare is an effect producer; undecided native dispatch stays named-loud."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
from dataclasses import dataclass

import pytest

from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import CallSiteValue, SymbolicValue, TermValue
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.ir import ctor, make_var
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.comparison_op_sugar import ComparisonOpSugar
from sugar_lift_py_tests.sugar.equality_op_sugar import EqualityOpSugar
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Compare
from sugar_source_tree.tree import SourceFile

# Content manifest (relative path + per-file BLAKE3-512). Path-shape
# sha256:a223… is historical negative testimony only — never identity.
MANIFEST_CID = (
    "blake3-512:6f317a5a489eb7e730064d79792f0d1656723130603309e2f2ed9cbedb604eda"
    "1c4b77a26dc90c980411292ea3994af9015da4cd850b5a307af5a4998b563530"
)
HISTORICAL_PATH_SHAPE_DIGEST = (
    "sha256:a223a4499d0909f22190748b4aca9144e35a58fec31e84cb924e2c25fd3c03d0"
)
DEMAND_TABLE_KEY = (
    "blake3-512:0ce7c645a7525f1fe5189b808162b49d3fc3ba3d898bfb3d5086e0f295b8b8d"
    "263fe7f530a6aa34adb125615a21e69fdee249e0314bf199b8f43580375153ab0"
)
COL_SITE_SHA256 = "a86bcccd3f041ac81a1d6f349d537ee1049c6afa4d799b9293b410da4409f038"
COL_SOURCE_CID = (
    "blake3-512:58f9629e47ef9bdb4137fbe31d1c322b22fd1918ec8da1b1725f344d0087d5a27"
    "f69cb188d8d417d0f6490c6a9531191e789f9e5df14e5070f93455673bacdad"
)
NUMERIC_SITE_SHA256 = "ad382bdf9178c34fffa4762b4014a8ef64d02e548433adaa8aba414398d6e5d8"
COMMON_SITE_SHA256 = "442441f4ea11ec95e361c54ddf5c599a49769928970af3daee3b9a482dce7754"
CATEGORICAL_EQ_SITE_SHA256 = (
    "b831a0a2339aaa702fc962a23f23b53e7f1eb08b45c6a93abddb42ee7e76690d"
)
MULTI_EQ_SITE_SHA256 = (
    "45fafbc8cd4dcc9bfcabd8f807e44e15377d729cfd7cf517c2b7ff72560aa343"
)


@dataclass(frozen=True)
class _ValueSugar(Sugar):
    value: object

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        del ctx
        return Complete(self.value)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _corpus_root() -> Path:
    corpus = authenticated_pandas_corpus()
    assert (corpus.version, corpus.manifest_cid, corpus.file_count) == (
        "3.0.3",
        MANIFEST_CID,
        1421,
    )
    assert corpus.manifest_cid != HISTORICAL_PATH_SHAPE_DIGEST
    return corpus.root


def _compare_at(path: Path, source: str, *, line: int) -> Compare:
    tree = SourceFile(
        (source, str(path), blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    matches = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, Compare) and node.line_col_span().start_line == line
    )
    assert len(matches) == 1
    return matches[0]


def _assert_named_compare_panic(node, *, observed: str) -> None:
    with pytest.raises(ConstructionPanic) as raised:
        node.sugar().desugar(None)
    info = raised.value.info
    assert info.owner == "comparison_operation_exception_floor"
    assert info.observed == observed
    assert "source-visible native comparison testimony" in info.requested
    assert "authenticated exceptional exit" in info.requested
    assert "TypeError" not in str(info)
    assert "RuntimeEffect" not in str(info)


def test_launcher_authenticates_content_manifest_not_path_shape() -> None:
    corpus = authenticated_pandas_corpus()
    assert corpus.manifest_cid == MANIFEST_CID
    assert corpus.manifest_cid != HISTORICAL_PATH_SHAPE_DIGEST
    assert corpus.file_count == 1421


def test_shared_table_authenticates_the_exact_compare_site(tmp_path: Path) -> None:
    output = tmp_path / "table.json"
    pulled = subprocess.run(
        [
            str(_repo_root() / "bin/sugarbin"),
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
        cwd=_repo_root(),
        capture_output=True,
        text=True,
        check=False,
        env={
            **dict(__import__("os").environ),
            "SUGAR_BINARY_ALLOW_BUILD": "0",
            "SUGAR_BINARY_PUBLISH": "0",
        },
    )
    assert pulled.returncode == 0 and output.is_file(), (
        "the authenticated #6464 demand table is absent; do not rebuild it: "
        + pulled.stderr
    )
    table = json.loads(output.read_text(encoding="utf-8"))
    assert table["authentication"]["python"] == "cpython-3.12.13"
    assert table["authentication"]["authenticatedCorpusManifestCid"] == MANIFEST_CID
    assert table["authentication"]["pandas"] == "3.0.3"
    assert table["identity"]["fileCount"] == 1421
    assert table["authentication"]["authenticatedCorpusManifestCid"] != (
        HISTORICAL_PATH_SHAPE_DIGEST
    )
    rows = tuple(
        row
        for row in table["rows"]
        if row.get("kind") == "context-manager-demand"
        and row.get("targetSymbol") == "pytest.raises"
        and row.get("gapKind") is None
        and row.get("useSite")
        == {
            "sourceCid": COL_SOURCE_CID,
            "startLine": 362,
            "startCol": 9,
            "endLine": 364,
            "endCol": 5,
        }
    )
    assert len(rows) == 1


def test_pandas_col_membership_refuses_to_invent_type_error() -> None:
    path = _corpus_root() / "tests/test_col.py"
    source = path.read_text(encoding="utf-8")
    assert hashlib.sha256(source.encode()).hexdigest() == COL_SITE_SHA256
    assert blake3_512_of(source.encode()) == COL_SOURCE_CID

    _assert_named_compare_panic(
        _compare_at(path, source, line=365),
        observed="TermValue in CallSiteValue",
    )


def test_literal_container_lying_twin_does_not_inherit_the_refusal() -> None:
    path = _corpus_root() / "tests/test_col.py"
    source = path.read_text(encoding="utf-8")
    lying = source.replace('1 in pd.col("a")', "1 in [1]")
    assert lying != source

    outcome = _compare_at(path, lying, line=365).sugar().desugar(None)

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, TrueBoolLiteralSugar)


def test_runtime_truthful_and_lying_twins_discriminate() -> None:
    import pandas as pd

    def raises_type_error(thunk) -> bool:
        try:
            thunk()
        except TypeError:
            return True
        return False

    with pytest.raises(TypeError, match="not .*iterable"):
        1 in pd.col("a")
    assert 1 in [1]
    with pytest.raises(AssertionError):
        assert raises_type_error(lambda: 1 in [1])


@pytest.mark.parametrize("op_kind", ["Lt", "NotEq", "In", "NotIn", "Eq"])
def test_every_nonidentity_comparison_keeps_undecided_call_dispatch_loud(
    op_kind: str,
) -> None:
    call_result = _ValueSugar(
        CallSiteValue("unknown", (), (), ctor("call:unknown", []), None)
    )
    ground = _ValueSugar(TermValue(1))
    left, right = (
        (ground, call_result)
        if op_kind in {"In", "NotIn"}
        else (
            call_result,
            ground,
        )
    )

    sugar = (
        EqualityOpSugar(left, right, "compare-site")
        if op_kind == "Eq"
        else ComparisonOpSugar(op_kind, left, right, "compare-site")
    )
    with pytest.raises(ConstructionPanic) as raised:
        sugar.desugar(None)

    assert raised.value.info.owner == "comparison_operation_exception_floor"
    assert "TypeError" not in str(raised.value.info)


@pytest.mark.parametrize("op_kind", ["Lt", "Gt", "LtE", "GtE"])
def test_undecided_symbolic_operands_refuse_invented_ordering(
    op_kind: str,
) -> None:
    """``left < right`` cannot invent ``py.lt`` when operand types are undecided."""
    left = _ValueSugar(SymbolicValue(make_var("left")))
    right = _ValueSugar(SymbolicValue(make_var("right")))
    with pytest.raises(ConstructionPanic) as raised:
        ComparisonOpSugar(op_kind, left, right, "compare-site").desugar(None)

    info = raised.value.info
    assert info.owner == "comparison_operation_exception_floor"
    operator = {"Lt": "<", "Gt": ">", "LtE": "<=", "GtE": ">="}[op_kind]
    assert info.observed == f"SymbolicValue {operator} SymbolicValue"
    assert "authenticated exceptional exit" in info.requested
    assert "TypeError" not in str(info)


def test_undecided_symbolic_equality_refuses_invented_py_eq() -> None:
    """``left == right`` cannot invent ``py.eq`` when both operand types are undecided.

    Misaligned pandas Index/Series/DataFrame/Categorical equality raises
    ValueError/TypeError at runtime. Emitting a total solver coordinate
    invents completion under ``pytest.raises``; inventing the exception
    invents an identity. Both stay refused until types are source-decided.
    """
    left = _ValueSugar(SymbolicValue(make_var("left")))
    right = _ValueSugar(SymbolicValue(make_var("right")))
    with pytest.raises(ConstructionPanic) as raised:
        EqualityOpSugar(left, right, "compare-site").desugar(None)

    info = raised.value.info
    assert info.owner == "comparison_operation_exception_floor"
    assert info.observed == "SymbolicValue == SymbolicValue"
    assert "authenticated exceptional exit" in info.requested
    assert "TypeError" not in str(info)
    assert "ValueError" not in str(info)


def test_symbolic_equality_with_ground_remains_solver_owned() -> None:
    """Symbolic/ground equality stays a total ``py.eq`` coordinate."""
    from sugar_lift_py_tests.floor.predicate_value import PredicateValue

    outcome = EqualityOpSugar(
        _ValueSugar(SymbolicValue(make_var("left"))),
        _ValueSugar(TermValue(1)),
        "compare-site",
    ).desugar(None)
    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, PredicateValue)


def test_ground_decided_equality_still_completes() -> None:
    """Lying twin: two decided ground scalars are not an undecided third value."""
    from sugar_lift_py_tests.floor.predicate_value import PredicateValue

    outcome = EqualityOpSugar(
        _ValueSugar(TermValue(1)),
        _ValueSugar(TermValue(2)),
        "compare-site",
    ).desugar(None)
    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, PredicateValue)


def test_undecided_symbolic_membership_refuses_invented_py_in() -> None:
    with pytest.raises(ConstructionPanic) as raised:
        ComparisonOpSugar(
            "In",
            _ValueSugar(TermValue(1)),
            _ValueSugar(SymbolicValue(make_var("container"))),
            "compare-site",
        ).desugar(None)

    info = raised.value.info
    assert info.owner == "comparison_operation_exception_floor"
    assert info.observed == "TermValue in SymbolicValue"
    assert "TypeError" not in str(info)


def test_ground_decided_membership_still_completes() -> None:
    """Lying twin: a decided finite container is not an undecided third value."""
    from sugar_lift_py_tests.floor import ListValue

    outcome = ComparisonOpSugar(
        "In",
        _ValueSugar(TermValue(1)),
        _ValueSugar(ListValue((TermValue(1),))),
        "compare-site",
    ).desugar(None)
    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, TrueBoolLiteralSugar)


def test_pandas_categorical_equality_stays_source_undecided() -> None:
    """``c1 == c2`` under TypeError: both Categorical types are source-undecided.

    Site: ``pandas/tests/arrays/categorical/test_operators.py:335``. Emitting
    ``py.eq`` invented the residual silent Complete; refuse without minting
    TypeError.
    """
    path = _corpus_root() / "tests/arrays/categorical/test_operators.py"
    source = path.read_text(encoding="utf-8")
    assert hashlib.sha256(source.encode()).hexdigest() == CATEGORICAL_EQ_SITE_SHA256
    assert source.count("c1 == c2") >= 1

    from pandas import Categorical

    c1 = Categorical(["a", "b"], categories=["a", "b"], ordered=False)
    c2 = Categorical(["a", "c"], categories=["c", "a"], ordered=False)
    with pytest.raises(TypeError, match="Categoricals can only be compared"):
        c1 == c2  # noqa: B015

    _assert_named_compare_panic(
        _compare_at(path, source, line=335),
        observed="SymbolicValue == SymbolicValue",
    )


def test_pandas_index_length_equality_stays_source_undecided() -> None:
    """``index_a == index_b`` under ValueError: length mismatch is not ``py.eq``."""
    path = _corpus_root() / "tests/indexes/multi/test_equivalence.py"
    source = path.read_text(encoding="utf-8")
    assert hashlib.sha256(source.encode()).hexdigest() == MULTI_EQ_SITE_SHA256

    _assert_named_compare_panic(
        _compare_at(path, source, line=43),
        observed="SymbolicValue == SymbolicValue",
    )


def test_source_decided_membership_in_number_emits_type_error() -> None:
    """``1 in 2`` is TypeError — numbers are never containers.

    Companion to enrolled membership under pytest.raises: when the container
    is a decided TermValue, Compare constructs RaiseValue rather than panicking
    on the contains floor.
    """
    from sugar_lift_py_tests.floor import RaiseValue

    twin = "def f():\n    return 1 in 2\n"
    tree = SourceFile(
        (twin, "in-number-twin.py", blake3_512_of(twin.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    node = next(
        n
        for n in tree.nodes()
        if isinstance(n, Compare) and n.line_col_span().start_line == 2
    )
    outcome = ComparisonOpSugar(
        "In",
        _ValueSugar(TermValue(1)),
        _ValueSugar(TermValue(2)),
        node.fragment,
    ).desugar(None)
    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, RaiseValue)
    assert outcome.value.effect.exception_name == "TypeError"


def test_source_decided_none_greater_than_emits_type_error() -> None:
    """``None > 1`` is TypeError on every ordering face, not a py.gt emit."""
    from sugar_lift_py_tests.floor import NoneValue, RaiseValue

    twin = "def f():\n    return None > 1\n"
    tree = SourceFile(
        (twin, "none-gt-twin.py", blake3_512_of(twin.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    node = next(
        n
        for n in tree.nodes()
        if isinstance(n, Compare) and n.line_col_span().start_line == 2
    )
    outcome = ComparisonOpSugar(
        "Gt",
        _ValueSugar(NoneValue()),
        _ValueSugar(TermValue(1)),
        node.fragment,
    ).desugar(None)
    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, RaiseValue)
    assert outcome.value.effect.exception_name == "TypeError"


def test_pandas_series_string_ordering_stays_source_undecided() -> None:
    """``obj < "a"``: string right is decided; left Series type is not.

    Site: ``pandas/tests/arithmetic/test_numeric.py:146`` under
    ``pytest.raises(TypeError)``. Source does not state Series type at the
    Compare, so the producer cannot mint TypeError — only the named refusal.
    """
    path = _corpus_root() / "tests/arithmetic/test_numeric.py"
    source = path.read_text(encoding="utf-8")
    assert hashlib.sha256(source.encode()).hexdigest() == NUMERIC_SITE_SHA256
    assert source.count('obj < "a"') == 1

    import pandas

    series = pandas.Series([1.0, 2.0], dtype="float64")
    with pytest.raises(TypeError, match="Invalid comparison"):
        series < "a"  # noqa: B015

    _assert_named_compare_panic(
        _compare_at(path, source, line=146),
        observed="SymbolicValue < StringValue",
    )


def test_source_decided_number_string_ordering_emits_type_error() -> None:
    """Truthful twin of the enrolled ``obj < "a"`` site with decided types.

    When both operands are source-visible ground values Python refuses to
    order, Compare constructs an authenticated TypeError RaiseValue — not
    ``py.lt`` and not a RuntimeEffect.  The enrolled pandas site still
    refuses because ``obj`` is undecided; this twin isolates the floor law
    on a workspace-relative locus the ground exit can cite.
    """
    from sugar_lift_py_tests.floor import RaiseValue, StringValue

    path = _corpus_root() / "tests/arithmetic/test_numeric.py"
    source = path.read_text(encoding="utf-8")
    assert source.count('obj < "a"') == 1
    _compare_at(path, source, line=146)

    twin = 'def f():\n    return 1.0 < "a"\n'
    tree = SourceFile(
        (twin, "number-lt-string-twin.py", blake3_512_of(twin.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    node = next(
        n
        for n in tree.nodes()
        if isinstance(n, Compare) and n.line_col_span().start_line == 2
    )
    outcome = ComparisonOpSugar(
        "Lt",
        _ValueSugar(TermValue(1.0)),
        _ValueSugar(StringValue("a")),
        node.fragment,
    ).desugar(None)

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, RaiseValue)
    assert outcome.value.effect.exception_name == "TypeError"
    assert outcome.value.effect.blame is not None


@pytest.mark.parametrize(
    ("line", "op", "observed"),
    (
        (144, "<", "SymbolicValue < SymbolicValue"),
        (146, "<=", "SymbolicValue <= SymbolicValue"),
        (148, ">", "SymbolicValue > SymbolicValue"),
        (150, ">=", "SymbolicValue >= SymbolicValue"),
        (152, "<", "SymbolicValue < SymbolicValue"),
        (154, "<=", "SymbolicValue <= SymbolicValue"),
        (156, ">", "SymbolicValue > SymbolicValue"),
        (158, ">=", "SymbolicValue >= SymbolicValue"),
    ),
)
def test_pandas_left_right_ordering_faces_stay_source_undecided(
    line: int, op: str, observed: str
) -> None:
    """``left < right`` family in arithmetic/common.py: both sides undecided.

    Eight faces of the same helper under TypeError expectations. Production
    construction sees only name coordinates — refuse without inventing exits.
    """
    path = _corpus_root() / "tests/arithmetic/common.py"
    source = path.read_text(encoding="utf-8")
    assert hashlib.sha256(source.encode()).hexdigest() == COMMON_SITE_SHA256
    _assert_named_compare_panic(
        _compare_at(path, source, line=line),
        observed=observed,
    )
    del op  # documented in parametrize for human readers of the tooth list
