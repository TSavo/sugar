"""Focused canonical SourceFile -> Backend materialization event contract.

This is deliberately not a repository census.  It pins one real source file,
one oracle intake, one SourceFile construction, and the one backend-owned
constructed-module event that is still missing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_source_tree.backend import Backend
from sugar_source_tree.reporter import CollectingReporter
from sugar_source_tree.tree import SourceFile


def test_from_path_enters_source_file_constructor_exactly_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = "VALUE = 1\n"
    path = tmp_path / "canonical-entry.py"
    path.write_text(source, encoding="utf-8")
    captured = []
    original_init = SourceFile.__init__

    def observe_init(self, identity, *args, **kwargs):
        captured.append(identity)
        return original_init(self, identity, *args, **kwargs)

    monkeypatch.setattr(SourceFile, "__init__", observe_init)
    SourceFile.from_path(path)

    assert len(captured) == 1
    captured_source, captured_filename, captured_source_cid = captured[0]
    assert captured_source == source
    assert captured_filename == str(path)
    assert isinstance(captured_source_cid, str) and captured_source_cid


def test_missing_backend_materialize_module_is_one_named_red() -> None:
    assert "materialize_module" in Backend.__dict__, (
        "R_missing_backend_materialize_module=1: Backend.materialize_module "
        "must own the sole SourceFile construction event"
    )


def test_canonical_source_file_stores_exactly_one_constructed_product(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if "materialize_module" not in Backend.__dict__:
        pytest.skip("dormant until R_missing_backend_materialize_module reaches zero")

    source = (
        "VALUE = 1\n"
        "def outer():\n"
        "    def child():\n"
        "        return VALUE\n"
        "    assert child() and external()\n"
    )
    path = tmp_path / "canonical-constructed-module.py"
    path.write_text(source, encoding="utf-8")
    calls = []
    original_door = Backend.materialize_module

    def observe_door(self, *args, **kwargs):
        product = original_door(self, *args, **kwargs)
        calls.append(product)
        return product

    monkeypatch.setattr(Backend, "materialize_module", observe_door)
    reporter = CollectingReporter()
    source_file = SourceFile.from_path(path, reporter=reporter)

    assert len(calls) == 1
    assert source_file.constructed_module is calls[0]
    assert source_file.root is calls[0].root
    assert source_file.closed_roll_call is calls[0].closed_roll_call
    child, external = calls[0].leaf_assertion_rows
    assert child.function_occurrence is external.function_occurrence
    assert child.assert_occurrence is external.assert_occurrence
    assert child.call_occurrence is not external.call_occurrence
    assert child.call_locus != external.call_locus
    assert child.construction_event_identity is (
        calls[0].construction_event_receipt.construction_event_identity
    )
    assert external.construction_event_identity is child.construction_event_identity
    assert all(
        any(registered is occurrence for registered in reporter.registered)
        for occurrence in (
            child.function_occurrence,
            child.assert_occurrence,
            child.call_occurrence,
            external.call_occurrence,
        )
    )
    for row in (child, external):
        assert not hasattr(row, "definition_occurrence")
        assert not hasattr(row, "lexical_scope")
    assert calls[0].construction_event_receipt.leaf_assertion_rows is (
        calls[0].leaf_assertion_rows
    )
    assert calls[0].construction_event_receipt.registered_occurrences == tuple(
        reporter.registered
    )
