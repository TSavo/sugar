"""One parse, one unit per file per session (#7757 item 5, follow-up to #8088).

The step-3 readers (the With rows and the lexical import pass) open a file
through the opener's first stage with no construction context, because their
rows are what the context's table is built from. The opener then opens the
same file under its context. Before this, the opener's open missed residency
(a different context) and parsed the file again: two parses, two units. Now
the opener attaches its context to the unit the readers parsed
(``SourceUnit.attach_construction_context``), once.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests import lift_rpc
from sugar_source_tree.nodes import SourceUnit
from sugar_source_tree.panic import BackendDefect
from sugar_source_tree.reporter import CollectingReporter

_PRODUCER = (
    "from contextlib import nullcontext\n"
    "\n"
    "\n"
    "def produce(carrier):\n"
    "    with nullcontext():\n"
    '        return carrier.mint(operator="floor_method")\n'
)


def _count_parses(monkeypatch: pytest.MonkeyPatch) -> list:
    bound: list = []
    original = SourceUnit.bind_typed_module

    def counted(self, module, **kwargs):
        bound.append(self.source_cid)
        return original(self, module, **kwargs)

    monkeypatch.setattr(SourceUnit, "bind_typed_module", counted)
    return bound


def test_the_readers_then_the_opener_parse_the_file_once_into_one_unit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sugar_lift_py_tests.import_binding import _run_lexical_import_pass

    path = tmp_path / "producer.py"
    path.write_text(_PRODUCER, encoding="utf-8")
    bound = _count_parses(monkeypatch)

    # Step 3: the With rows and the lexical import pass, through the first
    # stage with no context.
    rows = lift_rpc._context_manager_rows_for_paths([path], root=tmp_path)
    assert [row["kind"] for row in rows] == ["context-manager-demand"]
    source, _seat, source_cid = lift_rpc._read_at_seat(path, root=tmp_path)
    _run_lexical_import_pass(tmp_path, path, source, source_cid)
    read = lift_rpc._open_at_seat(path, root=tmp_path)
    assert read.unit.construction_context is None
    assert bound == [source_cid]

    opened = lift_rpc.open_source_file_for_construction(
        path, root=tmp_path, reporter=CollectingReporter()
    )

    assert bound == [source_cid], "the opener parsed the file a second time"
    assert opened is read
    assert opened.unit is read.unit
    assert opened.unit.construction_context is not None

    # A reader after the opener reads the opener's unit, and parses nothing.
    assert lift_rpc._open_at_seat(path, root=tmp_path).unit is opened.unit
    assert bound == [source_cid]


def test_the_context_a_caller_names_is_the_one_the_opener_builds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The audit leaf names the context; the enumerate levels do not. One open."""
    import sugar_lift_python_source.manager_summary_derivation as derivation

    path = tmp_path / "producer.py"
    path.write_text(_PRODUCER, encoding="utf-8")
    bound = _count_parses(monkeypatch)
    populated = []
    original_populate = derivation.populate_source_derived_resource_refs

    def counted_populate(source_file, **kwargs):
        populated.append(source_file.unit.filename)
        return original_populate(source_file, **kwargs)

    monkeypatch.setattr(
        derivation, "populate_source_derived_resource_refs", counted_populate
    )

    named = lift_rpc.construction_context_for_open(path, root=tmp_path)
    level = lift_rpc.open_source_file_for_construction(
        path, root=tmp_path, reporter=CollectingReporter()
    )
    leaf = lift_rpc.open_source_file_for_construction(
        path,
        root=tmp_path,
        reporter=CollectingReporter(),
        construction_context=named,
    )

    assert level.unit.construction_context is named
    assert leaf is level
    assert len(bound) == 1
    assert populated == ["producer.py"]


def test_a_unit_with_a_context_is_never_given_another(tmp_path: Path) -> None:
    """The slot is written once (#7772)."""
    path = tmp_path / "producer.py"
    path.write_text(_PRODUCER, encoding="utf-8")
    opened = lift_rpc.open_source_file_for_construction(path, root=tmp_path)
    context = opened.unit.construction_context

    with pytest.raises(BackendDefect):
        opened.unit.attach_construction_context(object())
    assert opened.unit.construction_context is context
