"""Subscript is an effect producer; unknown receiver types stay undecided."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import (
    CallSiteValue,
    ListValue,
    RaiseValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.ir import ctor, make_var
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.temporal import TemporalContext
from sugar_lift_python_source.source_oracle import workspace_path_source
from sugar_source_tree.tree import SourceFile

CORPUS_ROOT = Path(
    "/Users/tsavo/sugar-defect-drain/.venv/lib/python3.14/site-packages"
)
SITE = CORPUS_ROOT / "pandas/tests/test_multilevel.py"
SITE_SHA256 = "0308786b24b61a2b98be5d649e57ee847d7993ae1d0e1823d7f760408523131f"
MANIFEST_CID = "sha256:a223a4499d0909f22190748b4aca9144e35a58fec31e84cb924e2c25fd3c03d0"
DEMAND_TABLE_KEY = (
    "blake3-512:e225fcd0991f7c9011107521516e513390e448cc78ec4ce2da5eceb7116e1d89"
    "6cba3f8d9f19c1b5375692117a8395aa9f1529a63b768387ce9aeb43d8323499"
)


@pytest.fixture(scope="module")
def authenticated_site():
    assert hashlib.sha256(SITE.read_bytes()).hexdigest() == SITE_SHA256

    source = SourceFile(
        workspace_path_source(str(SITE), root=str(CORPUS_ROOT)),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    return next(
        node
        for node in source.nodes()
        if type(node).__name__ == "Subscript" and node.fragment.line == 158
    )


def test_shared_table_authenticates_the_exact_corpus(
    tmp_path: Path,
) -> None:
    output = tmp_path / "table.json"
    root = Path(__file__).resolve().parents[4]
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
            "cpython-3.14.4",
        ],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert pulled.returncode == 0, pulled.stderr
    table = json.loads(output.read_text(encoding="utf-8"))
    assert table["contentKey"] == DEMAND_TABLE_KEY
    assert table["authentication"]["authenticatedCorpusManifestCid"] == MANIFEST_CID

def test_real_pandas_unknown_receiver_is_named_undecided(authenticated_site) -> None:
    receiver = CallSiteValue(
        "source-constructor",
        (),
        (),
        ctor("call:source-constructor", []),
        None,
    )
    temporal = TemporalContext.empty().bind_value(
        "series", receiver
    )

    with pytest.raises(ConstructionPanic) as raised:
        authenticated_site.sugar().desugar(ReduceContext(temporal))

    assert raised.value.info.owner == "SymbolicValue.subscript"
    assert "undecided receiver runtime type" in raised.value.info.observed


def test_truthful_out_of_range_concrete_list_emits_index_error(
    authenticated_site,
) -> None:
    outcome = ListValue((TermValue(7),)).subscript(
        TermValue(1), authenticated_site.fragment
    )

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, RaiseValue)
    assert outcome.value.effect.exception_name == "IndexError"


def test_lying_in_range_concrete_list_does_not_emit_exception(
    authenticated_site,
) -> None:
    outcome = ListValue((TermValue(7),)).subscript(
        TermValue(0), authenticated_site.fragment
    )

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, TermValue)
    assert outcome.value.value == 7


def test_known_non_integer_list_index_emits_type_error(authenticated_site) -> None:
    outcome = ListValue((TermValue(7),)).subscript(
        TermValue(1.5), authenticated_site.fragment
    )

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, RaiseValue)
    assert outcome.value.effect.exception_name == "TypeError"


def test_unknown_list_index_is_a_named_third_value(authenticated_site) -> None:
    with pytest.raises(ConstructionPanic) as raised:
        ListValue((TermValue(7),)).subscript(
            SymbolicValue(make_var("index")), authenticated_site.fragment
        )

    assert raised.value.info.owner == "ListValue.subscript"
    assert "undecided" in raised.value.info.observed
