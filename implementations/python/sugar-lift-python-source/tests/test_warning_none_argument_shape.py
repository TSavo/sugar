"""Pinned real-site testimony for the inverted completed-warning boundary."""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.nodes import Call, Constant, With
from sugar_source_tree.tree import SourceFile


DEMAND_TABLE_CONTENT_KEY = (
    "blake3-512:e225fcd0991f7c9011107521516e513390e448cc78ec4ce2da5eceb7116e1d89"
    "6cba3f8d9f19c1b5375692117a8395aa9f1529a63b768387ce9aeb43d8323499"
)
FILE_SHA256 = "ef0819d48825f4614ec088f25b4d342a8808a12b1c5d45cff3281b481ec13252"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _corpus_file() -> Path:
    import pandas

    return Path(pandas.__file__).resolve().parent / "tests/series/test_constructors.py"


def _demand_rows(source_cid: str) -> tuple[dict, ...]:
    with tempfile.TemporaryDirectory() as scratch:
        output = Path(scratch) / "demand-table.json"
        completed = subprocess.run(
            [
                str(_repo_root() / "bin/sugarbin"),
                "artifact",
                "pull",
                "--kind",
                "python-demand-table",
                "--content-key",
                DEMAND_TABLE_CONTENT_KEY,
                "--output",
                str(output),
                "--runtime",
                "cpython-3.14.4",
            ],
            cwd=_repo_root(),
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0 and output.is_file(), completed.stderr
        payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["contentKey"] == DEMAND_TABLE_CONTENT_KEY
    return tuple(
        row
        for row in payload["rows"]
        if (row.get("useSite") or {}).get("sourceCid") == source_cid
    )


def test_real_pandas_back_to_back_none_warning_managers_are_distinct_native_sites():
    path = _corpus_file()
    source = path.read_text(encoding="utf-8")
    assert hashlib.sha256(source.encode("utf-8")).hexdigest() == FILE_SHA256
    source_cid = blake3_512_of(source.encode("utf-8"))
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (source, str(path), source_cid),
        construction_context=context,
    )

    sites = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, With)
        and node.line_col_span().start_line in {1290, 1296}
    )
    assert len(sites) == 2
    assert tuple(len(site.body) for site in sites) == (2, 1)
    for site in sites:
        manager = site.items[0].context_expr
        assert isinstance(manager, Call)
        assert len(manager.args) == 1
        assert isinstance(manager.args[0], Constant)
        assert manager.args[0].value is None

    rows = _demand_rows(source_cid)
    manager_rows = tuple(
        row
        for row in rows
        if (row.get("useSite") or {}).get("startLine") in {1290, 1296}
        and row.get("expectedKind") == "context-manager-contract"
    )
    assert tuple(
        (row["useSite"]["startLine"], row["useSite"]["startCol"])
        for row in manager_rows
    ) == ((1290, 13), (1296, 13))
    assert all(row.get("gapKind") is None for row in manager_rows)
