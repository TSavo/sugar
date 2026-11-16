"""Two present_construction lies that were not lies (2026-09-05 board, 17 rows).

- A lookup aid keyed by coordinates, walked as testimony, refused every
  value whose table was non-empty ("mappings require string keys", 8 rows).
  A field declared ``metadata={"testimony": "lookup"}`` is excluded from
  ConstructedValueV2.
- An in-population CLASS constructor call (``BooleanArray(...)``,
  ``OptionError(...)``: 9 rows) has a resolved definition and no constructor
  frame anywhere; that absence is honest testimony, never a mismatch.
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


@dataclass(frozen=True)
class _Authorized:
    name: str
    token: object = field(default=None, metadata={"testimony": "authority"})


@dataclass(frozen=True)
class _Unauthorized:
    name: str
    token: object = field(default=None)


def test_authority_field_is_excluded_from_testimony_and_plain_object_is_not() -> None:
    assert constructed_value_cid_v2(_Authorized("x", object())) == (
        constructed_value_cid_v2(_Authorized("x", object()))
    )
    with pytest.raises(ConstructedValueCategoryGap, match="builtins.object"):
        constructed_value_cid_v2(_Unauthorized("x", object()))


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
        construction_context=TreeConstructionContextV1.for_source_call_construction(),    )
    reporter = ConstructionTestimonyReporterV1(
        collector, SubstitutionTraceBuilderV1(source.unit.source_cid)
    )
    root = materialize(source.unit, source.root.ref, reporter)
    call = next(n for n in root.walk() if isinstance(n, Call))
    return call, reporter


def test_in_population_class_constructor_call_testifies(tmp_path) -> None:
    """Truthful twin: an in-population class call testifies.

    A call by name seats no definition's frame (#8958): the class call names
    no definition occurrence (its class value applies where it reduces), so
    the identity guard has nothing to ask and the honest absence testifies."""
    call, reporter = _class_constructor_call(tmp_path)
    sugar = call.sugar()
    assert not isinstance(getattr(sugar, "expected_definition_ref", None), ClassDef)
    reporter.present_construction(call, sugar)
    assert constructed_value_cid_v2(sugar).startswith("blake3-512:")
