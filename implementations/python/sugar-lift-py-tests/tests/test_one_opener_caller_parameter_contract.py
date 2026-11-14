"""One way to open a file (#7757 inventory item 5).

The caller-parameter contract used to open its files with a bare
``SourceFile.from_path``: an absolute seat, no construction context, no
population -- a different unit from the one the board reads. It now opens
through ``open_source_file_for_construction``, the call every board level
makes. A file it opens has the same unit identity and the same populated rows
as the same file opened with the board door's own arguments.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests import lift_rpc
from sugar_lift_py_tests.caller_parameter_contract import (
    _typed_minted_native_operator_constants,
)
from sugar_source_tree.reporter import CollectingReporter

_PRODUCER = (
    "from contextlib import nullcontext\n"
    "\n"
    "\n"
    "def produce(carrier):\n"
    "    with nullcontext():\n"
    '        return carrier.mint(operator="floor_method")\n'
)

_POPULATED_TABLES = (
    "source_derived_contract_refs",
    "source_call_frames",
    "opaque_source_call_obligations",
    "source_manager_provider_calls",
    "source_non_manager_heads",
)


def test_the_contract_reads_the_unit_the_board_door_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "producer.py"
    path.write_text(_PRODUCER, encoding="utf-8")

    original = lift_rpc.open_source_file_for_construction
    opened = []

    def recording(source_path, **kwargs):
        source_file = original(source_path, **kwargs)
        opened.append(source_file)
        return source_file

    monkeypatch.setattr(lift_rpc, "open_source_file_for_construction", recording)
    assert "floor_method" in _typed_minted_native_operator_constants(tmp_path)
    monkeypatch.setattr(lift_rpc, "open_source_file_for_construction", original)

    (contract_file,) = opened
    # The board door's arguments: a registration channel, the default context.
    board_file = original(path, root=tmp_path, reporter=CollectingReporter())

    # The same unit identity: one seat, one content address.
    assert contract_file.unit.filename == board_file.unit.filename == "producer.py"
    assert contract_file.unit.source_cid == board_file.unit.source_cid

    # The same authority and the same populated rows.
    contract_context = contract_file.unit.construction_context
    board_context = board_file.unit.construction_context
    assert contract_context is not None and board_context is not None
    assert contract_context.workspace_root == board_context.workspace_root
    assert (
        contract_context.contract_refs.table_cid
        == board_context.contract_refs.table_cid
    )
    for table in _POPULATED_TABLES:
        assert set(getattr(contract_context, table)) == set(
            getattr(board_context, table)
        ), table


def test_the_contract_opens_each_file_once_per_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Asking the question twice parses and populates each file once."""
    import sugar_lift_python_source.manager_summary_derivation as derivation

    path = tmp_path / "producer.py"
    path.write_text(_PRODUCER, encoding="utf-8")

    constructed = []
    populated = []
    original_open_at_seat = lift_rpc._open_at_seat
    original_populate = derivation.populate_source_derived_resource_refs

    def counted_open_at_seat(source_path, **kwargs):
        if kwargs.get("construction_context") is not None:
            constructed.append(Path(source_path))
        return original_open_at_seat(source_path, **kwargs)

    def counted_populate(source_file, **kwargs):
        populated.append(source_file.unit.filename)
        return original_populate(source_file, **kwargs)

    monkeypatch.setattr(lift_rpc, "_open_at_seat", counted_open_at_seat)
    monkeypatch.setattr(
        derivation, "populate_source_derived_resource_refs", counted_populate
    )

    first = _typed_minted_native_operator_constants(tmp_path)
    second = _typed_minted_native_operator_constants(tmp_path)

    assert first == second
    assert constructed == [path]
    assert populated == ["producer.py"]


def test_the_bare_doors_are_gone() -> None:
    """The extra entry points are deleted, not left beside the opener."""
    from sugar_source_tree.tree import SourceFile, SourceTree

    assert not hasattr(SourceFile, "from_module")
    assert not hasattr(SourceFile, "from_path")
    assert not hasattr(SourceTree, "files")
    assert not hasattr(lift_rpc, "_open_enumerated_file")
    assert not hasattr(lift_rpc, "_source_file_at_seat")
    assert not hasattr(lift_rpc, "_source_file_at_own_seat")
