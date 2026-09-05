"""Two present_construction lies that were not lies (2026-09-05 board, 17 rows).

- ``source_call_frame_table`` is a lookup aid keyed by coordinates; walking it
  as testimony refused every CallSiteSugar whose table was non-empty
  ("mappings require string keys", 8 rows). A field declared
  ``metadata={"testimony": "lookup"}`` is excluded from ConstructedValueV2.
- ``frame-is-none`` faulted every in-population CLASS constructor call
  (``BooleanArray(...)``, ``OptionError(...)``: 9 rows): the definition is
  resolved, no constructor frame exists anywhere, and the checker called
  that absence a mismatch. Absence is a lie only when the table seats a
  frame at this coordinate and the sugar dropped it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from sugar_lift_py_tests.context_manager_resolution import (
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
from sugar_source_tree.binding_state import (
    ConstructedValueCategoryGap,
    ConstructionTestimonyReporterV1,
    SubstitutionTraceBuilderV1,
    constructed_value_cid_v2,
)
from sugar_source_tree.nodes import Call, ClassDef
from sugar_source_tree.panic import ConstructedValueTestimonyNotWritten
from sugar_source_tree.reporter import CollectingReporter
from sugar_source_tree.backend import materialize


@dataclass(frozen=True)
class _Testified:
    name: str
    table: dict = field(default_factory=dict, metadata={"testimony": "lookup"})


@dataclass(frozen=True)
class _Walked:
    name: str
    table: dict = field(default_factory=dict)


def test_lookup_field_is_excluded_from_testimony_and_plain_field_is_not() -> None:
    key = SourceFragmentCoordinateV1("blake3-512:" + "ab" * 64, 1, 0, 1, 5)
    assert constructed_value_cid_v2(_Testified("x", {key: "frame"})) == (
        constructed_value_cid_v2(_Testified("x", {}))
    )
    with pytest.raises(ConstructedValueCategoryGap, match="require string keys"):
        constructed_value_cid_v2(_Walked("x", {key: "frame"}))


def _class_constructor_call(tmp_path):
    path = tmp_path / "ctor.py"
    path.write_text(
        "class Boom(ValueError):\n"
        "    pass\n\n"
        "def f(value):\n"
        "    raise Boom(value)\n"
    )
    collector = CollectingReporter()
    source = open_source_file_for_construction(
        path,
        root=tmp_path,
        reporter=collector,
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
        populate_derived=False,
    )
    reporter = ConstructionTestimonyReporterV1(
        collector, SubstitutionTraceBuilderV1(source.unit.source_cid)
    )
    root = materialize(source.unit, source.root.ref, reporter)
    call = next(n for n in root.walk() if isinstance(n, Call))
    return call, reporter


def test_in_population_class_constructor_call_testifies(tmp_path) -> None:
    """Truthful twin: resolved ClassDef, no constructor frame anywhere -> testimony."""
    call, reporter = _class_constructor_call(tmp_path)
    sugar = call.sugar()
    assert isinstance(sugar.expected_definition_ref, ClassDef)
    assert sugar.source_call_frame is None
    reporter.present_construction(call, sugar)  # was: frame-is-none
    assert constructed_value_cid_v2(sugar).startswith("blake3-512:")


def test_dropped_seated_frame_still_faults(tmp_path) -> None:
    """Lying twin: the table seats a frame at this coordinate, the sugar carries none."""
    from dataclasses import replace

    call, reporter = _class_constructor_call(tmp_path)
    sugar = call.sugar()
    span = call.line_col_span()
    coordinate = SourceFragmentCoordinateV1(
        call.unit.source_cid, span.start_line, span.start_col, span.end_line, span.end_col
    )
    lying = replace(
        sugar,
        source_call_frame=None,
        source_call_frame_table={coordinate: object()},
        source_call_frame_coordinate=coordinate,
        expected_source_call_frame_owner=sugar.expected_definition_ref,
    )
    with pytest.raises(ConstructedValueTestimonyNotWritten, match="frame-is-none"):
        reporter.present_construction(call, lying)
