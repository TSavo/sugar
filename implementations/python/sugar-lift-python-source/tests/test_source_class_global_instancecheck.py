"""Source call frames retain ordinary source-class globals used by isinstance."""

from __future__ import annotations

import csv
import enum
import importlib.metadata
import inspect
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sugar_lift_py_tests.floor import ObjectMethodValue
from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.callable_application import CallableApplication
from sugar_lift_py_tests.context_manager_resolution import SourceFragmentCoordinateV1
from sugar_lift_py_tests.import_binding import authenticated_import_use_receipts
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
from sugar_lift_py_tests.temporal.builtin_name_bindings import builtin_name_temporal
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
from sugar_lift_py_tests.sugar.call_site_sugar import (
    CallSiteSugar,
    _same_source_declaration,
    _seat_declaration_frame_globals,
    _with_frame_mutable_globals,
)
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.dependency_artifact import (
    DependencyArtifactGraph,
    ResolvedPythonObjectV1,
    resolve_import_binding,
)
from sugar_lift_python_source.manager_construction import resolve_source_visible_frame
from sugar_lift_python_source.manager_construction import _ModuleSourceFrameCallableV1
import sugar_lift_python_source.manager_construction as manager_construction
from sugar_source_tree.panic import BackendDefect
from sugar_lift_py_tests.gap.panic import ConstructionPanic


@dataclass(frozen=True)
class _FloorSugar(ConstructedTermSugar):
    value: object

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        del ctx
        return Complete(self.value)

    def to_term(self, *, owner):
        return self.value.to_term(owner=owner)

PROVIDER = (
    "class nonmember(object):\n"
    "    def __init__(self, value):\n"
    "        self.value = value\n"
    "def probe(value):\n"
    "    if isinstance(value, nonmember):\n"
    "        return value.value\n"
    "    return 2\n"
    "def locally_shadowed(value):\n"
    "    nonmember = value\n"
    "    return isinstance(value, nonmember)\n"
    "def nested_probe(value):\n"
    "    if isinstance(value, nonmember):\n"
    "        return value.value\n"
    "    return 2\n"
    "def outer_probe(value):\n"
    "    return nested_probe(value)\n"
)


def _distribution(root: Path) -> importlib.metadata.Distribution:
    package = root / "instancecheck_fixture"
    package.mkdir()
    (package / "__init__.py").write_text(PROVIDER, encoding="utf-8")
    metadata = root / "instancecheck_fixture-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: instancecheck-fixture\nVersion: 1.0\n",
        encoding="utf-8",
    )
    (metadata / "top_level.txt").write_text("instancecheck_fixture\n", encoding="utf-8")
    recorded = (
        "instancecheck_fixture/__init__.py",
        "instancecheck_fixture-1.0.dist-info/METADATA",
        "instancecheck_fixture-1.0.dist-info/top_level.txt",
        "instancecheck_fixture-1.0.dist-info/RECORD",
    )
    with (metadata / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for item in recorded:
            writer.writerow((item, "", ""))
    return importlib.metadata.Distribution.at(metadata)


def _frame(tmp_path: Path, symbol: str):
    dist = _distribution(tmp_path)
    graph = DependencyArtifactGraph.authenticate(dist)
    consumer = tmp_path / "consumer.py"
    source = f"from instancecheck_fixture import {symbol}\n{symbol}(None)\n"
    consumer.write_text(source, encoding="utf-8")
    receipts, _ = authenticated_import_use_receipts(
        tmp_path,
        consumer,
        source,
        blake3_512_of(source.encode("utf-8")),
        module_identities={},
    )
    resolved = resolve_import_binding(receipts[0], graph=graph)
    assert isinstance(resolved, ResolvedPythonObjectV1)
    projected = resolve_source_visible_frame(resolved, graph=graph)
    assert isinstance(projected, tuple)
    frame, target = projected
    assert target.name == symbol
    return frame


def test_enum_nonmember_global_decides_object_method_false(tmp_path: Path) -> None:
    """The real false face reaches ``_is_descriptor``; it never reads `.value`."""
    frame = _frame(tmp_path, "probe")
    bindings = frame.source_class_bindings

    assert tuple(binding.name for binding in bindings) == ("nonmember",)
    assert replace(frame, source_class_bindings=()).frame_cid != frame.frame_cid
    nonmember = bindings[0].value
    assert nonmember.ordinary_instancecheck is True
    method = ObjectMethodValue(
        "member",
        ("self",),
        TrueBoolLiteralSugar(site="method-site"),
        "blake3-512:" + "7" * 128,
    )

    outcome = nonmember.test_python_type(method, "Lib/enum.py:446:13")

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, FalseBoolLiteralSugar)

    occurrence = SourceFragmentCoordinateV1(frame.source_identity_cid, 20, 0, 20, 12)
    called = CallableApplication(
        (method,),
        (),
        occurrence,
        owner="enum nonmember frame tooth",
        call_occurrence=occurrence,
    ).apply(_ModuleSourceFrameCallableV1("probe", frame), None)
    assert isinstance(called, Complete)
    assert called.value.value == 2

    stripped = replace(frame, source_class_bindings=())
    called_from_stripped = CallSiteSugar(
        target_name="probe",
        args=(_FloorSugar(method),),
        site="stripped enum nonmember frame tooth",
        source_call_frame=stripped,
        call_occurrence=occurrence,
    ).desugar(None)
    assert isinstance(called_from_stripped, Complete)
    projected = called_from_stripped.value.project_operation_receiver(
        None, owner="stripped enum nonmember frame tooth"
    )
    assert projected.value == 2

    callsite_ctx = _with_frame_mutable_globals(None, frame)
    assert callsite_ctx.temporal.value_if_bound("nonmember") is nonmember
    assert callsite_ctx.module_temporal.value_if_bound("nonmember") is nonmember


def test_real_cpython_312_enum_method_is_not_an_instance_of_type(
    tmp_path: Path,
) -> None:
    """The real ``_EnumDict.__setitem__`` function cannot enter a class face."""
    assert sys.version_info[:2] == (3, 12), (
        "this law authenticates the declared CPython 3.12 stdlib source"
    )
    source = inspect.getsource(enum.nonmember) + "\n" + inspect.getsource(enum._EnumDict)
    path = tmp_path / "enum_312_slice.py"
    path.write_text(source, encoding="utf-8")
    tree = open_source_file_for_construction(
        path, root=tmp_path, populate_derived=False
    )
    enum_dict = next(
        node
        for node in tree.nodes()
        if node.kind == "ClassDef" and node.name == "_EnumDict"
    )
    constructed = enum_dict.sugar().desugar(
        ReduceContext(temporal=builtin_name_temporal())
    )
    assert isinstance(constructed, Complete)
    receiver = constructed.value.construct_receiver_state_from_block(
        None, "real-cpython-312-enumdict-receiver"
    )
    method = next(item for item in receiver.methods if item.name == "__setitem__")
    assert isinstance(method, ObjectMethodValue)
    assert method.source_call_frame_cid is not None

    type_class = builtin_name_temporal().value_if_bound("type")
    outcome = type_class.test_python_type(method, "enum.py:_EnumDict.__setitem__")

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, FalseBoolLiteralSugar)
    object_class = builtin_name_temporal().value_if_bound("object")
    object_outcome = object_class.test_python_type(
        method, "enum.py:_EnumDict.__setitem__:object"
    )
    assert isinstance(object_outcome, Complete)
    assert isinstance(object_outcome.value, TrueBoolLiteralSugar)

    unauthenticated = replace(method, source_call_frame_cid=None)
    with pytest.raises(ConstructionPanic) as raised:
        type_class.test_python_type(
            unauthenticated, "enum.py:_EnumDict.__setitem__:lying"
        )
    assert raised.value.info.owner == "ObjectMethodValue.python_isinstance"


def test_local_nonmember_shadow_cannot_borrow_module_class_authority(
    tmp_path: Path,
) -> None:
    """Lying arm: a local binding excludes the same-spelled module class."""
    frame = _frame(tmp_path, "locally_shadowed")

    assert all(binding.name != "nonmember" for binding in frame.source_class_bindings)


def test_context_enrichment_preserves_declaration_identity(tmp_path: Path) -> None:
    """Distinct frame CIDs may truthfully retain one source declaration."""
    enriched = _frame(tmp_path, "probe")
    bare = replace(enriched, source_class_bindings=())

    assert enriched.frame_cid != bare.frame_cid
    assert _same_source_declaration(enriched, bare)
    merged = _seat_declaration_frame_globals(
        None,
        installed_frame=enriched,
        declaration_frame=enriched,
        blame="duplicate-global-tooth",
    )
    assert merged.temporal.value_if_bound("nonmember") is enriched.source_class_bindings[0].value


def test_different_source_declarations_cannot_share_body_authority(
    tmp_path: Path,
) -> None:
    """Lying arm: source/name proximity cannot replace declaration identity."""
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()
    probe = _frame(left, "probe")
    shadowed = _frame(right, "locally_shadowed")

    assert not _same_source_declaration(probe, shadowed)


def test_conflicting_same_name_global_testimony_is_not_last_wins() -> None:
    """Lying arm: regenerated globals cannot overwrite an installed witness."""
    occurrence = SimpleNamespace(source_cid="source")
    installed_binding = SimpleNamespace(
        name="nonmember",
        definition_occurrence=occurrence,
        class_definition_cid="blake3-512:" + "1" * 128,
    )
    declaration_binding = SimpleNamespace(
        name="nonmember",
        definition_occurrence=occurrence,
        class_definition_cid="blake3-512:" + "2" * 128,
    )
    installed = SimpleNamespace(
        mutable_global_bindings=(),
        decorated_class_bindings=(),
        source_class_bindings=(installed_binding,),
    )
    declaration = SimpleNamespace(
        mutable_global_bindings=(),
        decorated_class_bindings=(),
        source_class_bindings=(declaration_binding,),
    )

    with pytest.raises(BackendDefect, match="conflicting source global testimony"):
        _seat_declaration_frame_globals(
            None,
            installed_frame=installed,
            declaration_frame=declaration,
            blame="conflicting-global-tooth",
        )


def test_reachable_nested_frame_carries_its_own_source_class_global(
    tmp_path: Path,
) -> None:
    """A nested reachable function is enriched before its frame is installed."""
    installed = []
    original_install = manager_construction._install_source_call_frame

    def record_install(context, call, frame):
        installed.append(frame)
        return original_install(context, call, frame)

    with patch.object(
        manager_construction,
        "_install_source_call_frame",
        side_effect=record_install,
    ):
        _frame(tmp_path, "outer_probe")

    nested_frame = next(
        frame for frame in installed if frame.owner.name == "nested_probe"
    )
    assert tuple(binding.name for binding in nested_frame.source_class_bindings) == (
        "nonmember",
    )
    method = ObjectMethodValue(
        "member",
        ("self",),
        TrueBoolLiteralSugar(site="nested-method-site"),
        "blake3-512:" + "8" * 128,
    )
    occurrence = SourceFragmentCoordinateV1(
        nested_frame.source_identity_cid, 30, 0, 30, 12
    )

    called = CallableApplication(
        (method,),
        (),
        occurrence,
        owner="nested source class frame tooth",
        call_occurrence=occurrence,
    ).apply(_ModuleSourceFrameCallableV1("nested_probe", nested_frame), None)

    assert isinstance(called, Complete)
    assert called.value.value == 2


def test_class_method_frame_uses_same_source_class_global_authority(
    tmp_path: Path,
) -> None:
    """ClassDef's direct method-frame door cannot bypass global enrichment."""
    source = (
        "class nonmember(object):\n"
        "    pass\n"
        "class Holder(object):\n"
        "    def method(self, value):\n"
        "        return isinstance(value, nonmember)\n"
        "class ShadowHolder(object):\n"
        "    def method(self, value):\n"
        "        nonmember = value\n"
        "        return isinstance(value, nonmember)\n"
    )
    path = tmp_path / "class_method_frame.py"
    path.write_text(source, encoding="utf-8")
    tree = open_source_file_for_construction(
        path, root=tmp_path, populate_derived=False
    )
    classes = {
        node.name: node
        for node in tree.nodes()
        if node.kind == "ClassDef" and node.name in {"Holder", "ShadowHolder"}
    }
    ctx = ReduceContext(temporal=builtin_name_temporal())
    holder = classes["Holder"].sugar().desugar(ctx)
    shadow = classes["ShadowHolder"].sugar().desugar(ctx)
    assert isinstance(holder, Complete)
    assert isinstance(shadow, Complete)
    holder_frame = next(
        method.source_call_frame
        for method in holder.value.methods
        if method.name == "method"
    )
    shadow_frame = next(
        method.source_call_frame
        for method in shadow.value.methods
        if method.name == "method"
    )

    assert tuple(binding.name for binding in holder_frame.source_class_bindings) == (
        "nonmember",
    )
    assert shadow_frame.source_class_bindings == ()


def test_enclosing_class_is_not_eagerly_published_into_its_own_method_frame(
    tmp_path: Path,
) -> None:
    """A DictWrapper-shaped self global is later than its method definition."""
    source = (
        "class earlier(object):\n"
        "    pass\n"
        "class DictWrapper(object):\n"
        "    def __getattr__(self, key):\n"
        "        if isinstance(key, earlier):\n"
        "            return DictWrapper(key)\n"
        "        return key\n"
    )
    path = tmp_path / "self_class_global.py"
    path.write_text(source, encoding="utf-8")
    tree = open_source_file_for_construction(
        path, root=tmp_path, populate_derived=False
    )
    wrapper = next(
        node for node in tree.nodes() if node.kind == "ClassDef" and node.name == "DictWrapper"
    )

    constructed = wrapper.sugar().desugar(
        ReduceContext(temporal=builtin_name_temporal())
    )

    assert isinstance(constructed, Complete)
    frame = next(
        method.source_call_frame
        for method in constructed.value.methods
        if method.name == "__getattr__"
    )
    assert tuple(binding.name for binding in frame.source_class_bindings) == (
        "earlier",
    )
