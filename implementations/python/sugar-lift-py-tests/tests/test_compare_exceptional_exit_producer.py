"""Compare is an effect producer; membership follows native source testimony."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
from dataclasses import dataclass

import pytest

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import CallSiteValue, TermValue
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.ir import ctor
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.comparison_op_sugar import ComparisonOpSugar
from sugar_lift_py_tests.sugar.equality_op_sugar import EqualityOpSugar
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.source_oracle import workspace_path_source
from sugar_source_tree.nodes import Compare
from sugar_source_tree.tree import SourceFile

CORPUS_ROOT = Path("/Users/tsavo/sugar-defect-drain/.venv/lib/python3.14/site-packages")
SITE = CORPUS_ROOT / "pandas/tests/test_col.py"
SITE_SHA256 = "a86bcccd3f041ac81a1d6f349d537ee1049c6afa4d799b9293b410da4409f038"
SOURCE_CID = (
    "blake3-512:58f9629e47ef9bdb4137fbe31d1c322b22fd1918ec8da1b1725f344d0087d5a27"
    "f69cb188d8d417d0f6490c6a9531191e789f9e5df14e5070f93455673bacdad"
)
MANIFEST_CID = (
    "blake3-512:6f317a5a489eb7e730064d79792f0d1656723130603309e2f2ed9cbedb604eda"
    "1c4b77a26dc90c980411292ea3994af9015da4cd850b5a307af5a4998b563530"
)
DEMAND_TABLE_KEY = (
    "blake3-512:0ce7c645a7525f1fe5189b808162b49d3fc3ba3d898bfb3d5086e0f295b8b8d"
    "263fe7f530a6aa34adb125615a21e69fdee249e0314bf199b8f43580375153ab0"
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


def _compare_at_365(source: str) -> Compare:
    source_identity = (
        workspace_path_source(str(SITE), root=str(CORPUS_ROOT))
        if hashlib.sha256(source.encode()).hexdigest() == SITE_SHA256
        else (source, str(SITE), blake3_512_of(source.encode()))
    )
    tree = SourceFile(
        source_identity,
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    matches = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, Compare) and node.line_col_span().start_line == 365
    )
    assert len(matches) == 1
    return matches[0]


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
    rows = tuple(
        row
        for row in table["rows"]
        if row.get("kind") == "context-manager-demand"
        and row.get("targetSymbol") == "pytest.raises"
        and row.get("gapKind") is None
        and row.get("useSite")
        == {
            "sourceCid": SOURCE_CID,
            "startLine": 362,
            "startCol": 9,
            "endLine": 364,
            "endCol": 5,
        }
    )
    assert len(rows) == 1


def test_pandas_col_membership_refuses_to_invent_type_error() -> None:
    source = SITE.read_text(encoding="utf-8")
    assert hashlib.sha256(source.encode()).hexdigest() == SITE_SHA256

    with pytest.raises(ConstructionPanic) as raised:
        _compare_at_365(source).sugar().desugar(None)

    info = raised.value.info
    assert info.owner == "comparison_operation_exception_floor"
    assert info.observed == "TermValue in CallSiteValue"
    assert "source-visible native comparison testimony" in info.requested
    assert "TypeError" not in str(info)


def test_literal_container_lying_twin_does_not_inherit_the_refusal() -> None:
    source = SITE.read_text(encoding="utf-8")
    lying = source.replace('1 in pd.col("a")', "1 in [1]")
    assert lying != source

    outcome = _compare_at_365(lying).sugar().desugar(None)

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


@pytest.mark.parametrize("op_kind", ["Lt", "NotEq", "In", "NotIn"])
def test_every_nonidentity_comparison_keeps_undecided_dispatch_loud(
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

    with pytest.raises(ConstructionPanic) as raised:
        ComparisonOpSugar(op_kind, left, right, "compare-site").desugar(None)

    assert raised.value.info.owner == "comparison_operation_exception_floor"
    assert "TypeError" not in str(raised.value.info)


def test_equality_keeps_undecided_native_dispatch_loud() -> None:
    with pytest.raises(ConstructionPanic) as raised:
        EqualityOpSugar(
            _ValueSugar(
                CallSiteValue("unknown", (), (), ctor("call:unknown", []), None)
            ),
            _ValueSugar(TermValue(1)),
            "compare-site",
        ).desugar(None)

    assert raised.value.info.owner == "comparison_operation_exception_floor"
    assert "TypeError" not in str(raised.value.info)
