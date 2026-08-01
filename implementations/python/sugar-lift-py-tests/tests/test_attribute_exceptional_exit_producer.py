"""Attribute lookup is an effect producer; undecided lookup stays named-loud."""

from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import mmap
from pathlib import Path
import subprocess

import pytest

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import CallSiteValue, NoneValue, SymbolicValue
from sugar_source_tree.panic import SugarNotWritten
from sugar_lift_py_tests.ir import ctor, make_var
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.source_oracle import workspace_path_source
from sugar_source_tree.nodes import Attribute
from sugar_source_tree.tree import SourceFile


from sugar_lift_py_tests.repo_root import resolve_repo_root

SITE_SHA256 = "4d2599448c6b329af3822dbc2295fafe142d9ce84e49821c435d9b1c11fea793"
SOURCE_CID = (
    "blake3-512:43cdd8a4f204ef75c77996a7e7a98b84bcd174de708cfe1e9e430415bbd636e2"
    "186f44518e941e76854029b14db48605c43ff6c242c0750322c215eb7c646013"
)
MANIFEST_CID = (
    "blake3-512:6f317a5a489eb7e730064d79792f0d1656723130603309e2f2ed9cbedb604eda"
    "1c4b77a26dc90c980411292ea3994af9015da4cd850b5a307af5a4998b563530"
)
DEMAND_TABLE_KEY = (
    "blake3-512:0ce7c645a7525f1fe5189b808162b49d3fc3ba3d898bfb3d5086e0f295b8b8d"
    "263fe7f530a6aa34adb125615a21e69fdee249e0314bf199b8f43580375153ab0"
)


def _repo_root() -> Path:
    return resolve_repo_root()


def _site_attribute(source: str, site: Path) -> Attribute:
    assert blake3_512_of(source.encode()) == SOURCE_CID
    tree = SourceFile(
        workspace_path_source(str(site), root=str(site.parents[2])),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    matches = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, Attribute)
        and node.attr == "bad"
        and node.line_col_span().start_line == 104
    )
    assert len(matches) == 1
    return matches[0]


def _call_result() -> CallSiteValue:
    return CallSiteValue(
        "source-constructor",
        (),
        (),
        ctor("call:source-constructor", []),
        None,
    )


@dataclass(frozen=True)
class _ReceiverSugar(Sugar):
    value: object

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        del ctx
        return Complete(self.value)


def _assert_undecided(node: Attribute, receiver, *, name: str | None = None) -> None:
    operation = replace(
        node.sugar(),
        receiver=_ReceiverSugar(receiver),
        name=node.attr if name is None else name,
    )
    with pytest.raises(SugarNotWritten) as raised:
        operation.desugar(None)
    refusal = raised.value
    assert refusal.blame == node.fragment
    assert f"{node.fragment.filename}:{node.fragment.line}:{node.fragment.col}" in str(
        refusal
    )
    assert refusal.owner == f"{type(receiver).__name__}.attribute"
    assert "undecided" in refusal.observed
    assert "source-authenticated attribute success or exceptional exit" in (
        refusal.requested
    )
    assert "AttributeError" not in refusal.observed
    assert "AttributeError" not in refusal.requested
    assert "RuntimeEffect" not in refusal.observed
    assert "RuntimeEffect" not in refusal.requested


def test_shared_table_authenticates_the_exact_assertion_manager(tmp_path: Path) -> None:
    output = tmp_path / "python-demand-table.json"
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
    with output.open("rb") as table_file, mmap.mmap(
        table_file.fileno(), 0, access=mmap.ACCESS_READ
    ) as table:
        assert table.find(DEMAND_TABLE_KEY.encode()) >= 0
        assert table.find(b'"python": "cpython-3.12.13"') >= 0
        assert table.find(MANIFEST_CID.encode()) >= 0
        assert table.find(b'"pandas": "3.0.3"') >= 0
        assert table.find(b'"fileCount": 1421') >= 0
        cursor = 0
        rows = []
        while True:
            cursor = table.find(b'"startLine": 103', cursor)
            if cursor < 0:
                break
            window = table[max(0, cursor - 5000) : cursor + 5000]
            if (
                SOURCE_CID.encode() in window
                and b'"kind": "context-manager-demand"' in window
                and b'"targetSymbol": "pytest.raises"' in window
                and b'"gapKind": null' in window
                and b'"startCol": 13' in window
                and b'"endCol": 58' in window
            ):
                rows.append(cursor)
            cursor += 1
        assert len(rows) >= 1


def test_real_pandas_constructed_receiver_attribute_is_named_undecided() -> None:
    site = _authenticated_corpus_file("tests/test_register_accessor.py")
    source = site.read_text(encoding="utf-8")
    assert hashlib.sha256(source.encode()).hexdigest() == SITE_SHA256
    node = _site_attribute(source, site)

    _assert_undecided(node, _call_result())


def test_symbolic_receiver_attribute_is_the_same_named_third_value() -> None:
    site = _authenticated_corpus_file("tests/test_register_accessor.py")
    source = site.read_text(encoding="utf-8")
    node = _site_attribute(source, site)

    _assert_undecided(node, SymbolicValue(make_var("series")))


def test_lying_known_member_does_not_license_blanket_attribute_error() -> None:
    outcome = NoneValue().attribute("__class__", "lying-none-class")

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, SymbolicValue)


def test_replacing_bad_with_known_member_still_cannot_invent_an_exit() -> None:
    site = _authenticated_corpus_file("tests/test_register_accessor.py")
    source = site.read_text(encoding="utf-8")
    assert source.count("pd.Series([], dtype=object).bad") == 1
    lying = source.replace(
        "pd.Series([], dtype=object).bad",
        "pd.Series([], dtype=object).__class__",
    )
    assert "pd.Series([], dtype=object).__class__" in lying

    _assert_undecided(_site_attribute(source, site), _call_result(), name="__class__")


# --- No-call Attribute family corpus pins (denominator 41) -----------------
# Bare desugar without bindings yields SymbolicValue receivers; the producer
# must keep the third value as SugarNotWritten(owner=SymbolicValue.attribute)
# rather than invent AttributeError. These sites are enrolled Attribute bodies
# under the no-Call-descendant law.


def _authenticated_corpus_file(relative: str) -> Path:
    from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus

    corpus = authenticated_pandas_corpus()
    assert (corpus.version, corpus.manifest_cid, corpus.file_count) == (
        "3.0.3",
        MANIFEST_CID,
        1421,
    )
    return corpus.root / relative


def _line_attribute(source: str, path: Path, *, line: int, attr: str) -> Attribute:
    source_cid = blake3_512_of(source.encode("utf-8"))
    tree = SourceFile(
        (source, str(path), source_cid),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    matches = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, Attribute)
        and node.attr == attr
        and node.line_col_span().start_line == line
    )
    assert len(matches) == 1
    return matches[0]


def _assert_bare_desugar_symbolic_attribute(node: Attribute) -> None:
    """Production door: expression.sugar().desugar(None) with no bindings."""
    with pytest.raises(SugarNotWritten) as raised:
        node.sugar().desugar(None)
    refusal = raised.value
    assert refusal.owner == "SymbolicValue.attribute"
    assert "undecided" in refusal.observed
    assert "source-authenticated attribute success or exceptional exit" in (
        refusal.requested
    )
    assert "AttributeError" not in refusal.observed
    assert "AttributeError" not in refusal.requested
    assert "RuntimeEffect" not in refusal.observed
    assert "RuntimeEffect" not in refusal.requested


@pytest.mark.parametrize(
    "relative,line,attr,snippet",
    [
        ("tests/series/test_api.py", 175, "foo", "ser.foo"),
        ("tests/series/test_api.py", 195, "weekday", "ser.weekday"),
        ("tests/api/test_api.py", 491, "foo", "pd.util.foo"),
        ("tests/strings/test_api.py", 88, "str", "mi.str"),
        ("tests/series/accessors/test_cat_accessor.py", 65, "cat", "invalid.cat"),
        ("tests/arrays/sparse/test_accessor.py", 97, "density", "ser.sparse.density"),
    ],
)
def test_no_call_attribute_corpus_sites_stay_symbolic_undecided(
    relative: str, line: int, attr: str, snippet: str
) -> None:
    path = _authenticated_corpus_file(relative)
    source = path.read_text(encoding="utf-8")
    assert snippet in source
    node = _line_attribute(source, path, line=line, attr=attr)
    _assert_bare_desugar_symbolic_attribute(node)


def test_binop_child_np_nan_reattributes_to_attribute_owner() -> None:
    """BinOp ``s_0123 & np.nan`` child-evaluates ``.nan`` on SymbolicValue.

    That refusal is Attribute-family coordinate (owner SymbolicValue.attribute),
    not binary_operation_exception_floor. Keep the owner name honest when a
    BinOp site is a parent of Attribute evaluation.
    """
    path = _authenticated_corpus_file("tests/series/test_logical_ops.py")
    source = path.read_text(encoding="utf-8")
    assert source.count("s_0123 & np.nan") == 1
    source_cid = blake3_512_of(source.encode("utf-8"))
    tree = SourceFile(
        (source, str(path), source_cid),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    from sugar_source_tree.nodes import BinOp

    matches = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, BinOp)
        and node.op.kind == "BitAnd"
        and node.line_col_span().start_line == 96
    )
    assert len(matches) == 1
    with pytest.raises(SugarNotWritten) as raised:
        matches[0].sugar().desugar(None)
    refusal = raised.value
    assert refusal.owner == "SymbolicValue.attribute"
    assert "SymbolicValue.nan" in refusal.observed
    assert "source-authenticated attribute success or exceptional exit" in (
        refusal.requested
    )
