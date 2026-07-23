from __future__ import annotations

import csv
import importlib.metadata
from pathlib import Path

from sugar_lift_py_tests.floor import BlockValue, CallSiteValue, ReturnValue, TermValue
from sugar_lift_py_tests.import_binding import authenticated_import_use_receipts
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.dependency_artifact import (
    DependencyArtifactGraph,
    ResolvedPythonObjectV1,
    resolve_import_binding,
)
from sugar_lift_python_source.manager_construction import (
    ConstructedCallActualV1,
    ConstructedManagerBehaviorV1,
    ManagerConstructionGapV1,
    construct_manager_behavior,
)
from sugar_lift_python_source.manager_protocol_construction import (
    ConstructedManagerProtocolV1,
    ManagerProtocolConstructionGapV1,
    construct_manager_protocol,
)
from sugar_lift_python_source.manager_summary_derivation import (
    DerivedManagerSummaryGapV1,
    DerivedManagerSummaryV1,
    derive_manager_summary,
    populate_source_derived_resource_refs,
)
from sugar_source_tree.binding_provenance import ConstructedValueTestimonyV1
from sugar_source_tree.binding_state import BindingEntryV1
from sugar_source_tree.nodes import Call, Constant
from sugar_source_tree.tree import SourceFile


def _distribution(
    root: Path, source: str, *, exported: str = "make_guard"
) -> importlib.metadata.Distribution:
    package = root / "arbitrary"
    package.mkdir()
    (package / "__init__.py").write_text(
        f"from arbitrary.manager import {exported}\n", encoding="utf-8"
    )
    (package / "manager.py").write_text(source, encoding="utf-8")
    metadata = root / "arbitrary_dist-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: arbitrary-dist\nVersion: 1.0\n",
        encoding="utf-8",
    )
    files = (
        "arbitrary/__init__.py",
        "arbitrary/manager.py",
        "arbitrary_dist-1.0.dist-info/METADATA",
        "arbitrary_dist-1.0.dist-info/RECORD",
    )
    with (metadata / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for file in files:
            writer.writerow((file, "", ""))
    return importlib.metadata.Distribution.at(metadata)


def _resolved(root: Path, source: str, *, exported: str = "make_guard"):
    graph = DependencyArtifactGraph.authenticate(
        _distribution(root, source, exported=exported)
    )
    consumer = f"import arbitrary\narbitrary.{exported}(23)\n"
    path = root / "consumer.py"
    path.write_text(consumer, encoding="utf-8")
    source_cid = blake3_512_of(consumer.encode())
    receipts, _ = authenticated_import_use_receipts(root, path, consumer, source_cid)
    resolved = resolve_import_binding(receipts[0], graph=graph)
    assert isinstance(resolved, ResolvedPythonObjectV1)
    source_file = SourceFile((consumer, str(path), source_cid))
    call = next(item for item in source_file.nodes() if isinstance(item, Call))
    literal = next(item for item in call.args if isinstance(item, Constant))
    actual = TermValue(23)
    # Testimony uses the canonical term address, never repr spelling.
    from sugar_lift_py_tests.ir import _term_content_cid

    testimony = ConstructedValueTestimonyV1.mint(
        literal.fragment, _term_content_cid(actual.to_term(owner="test"))
    )
    return (
        graph,
        resolved,
        ConstructedCallActualV1(literal, actual, testimony),
        call.fragment,
    )


def test_renamed_factory_constructs_returned_receiver_state_through_one_door(tmp_path):
    graph, resolved, actual, call_site = _resolved(
        tmp_path,
        "class UnprivilegedGuard:\n"
        "    def __init__(self, expected):\n"
        "        self.expected = expected\n\n"
        "def make_guard(expected):\n"
        "    return UnprivilegedGuard(expected)\n",
    )

    result = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=call_site
    )

    assert isinstance(result, ConstructedManagerBehaviorV1)
    fields = {field.name: field.value for field in result.receiver_state.fields}
    assert fields == {"expected": actual.value}
    entry = result.formal_actual_bindings[0]
    assert isinstance(entry, BindingEntryV1)
    assert entry.state is actual.node
    assert entry.coordinate.projection_path == ("formal", 0)
    assert "node" not in repr(entry.wire()).lower()
    assert result.manager_construction_cid.startswith("blake3-512:")


def test_opaque_source_call_stays_typed_loud(tmp_path):
    graph, resolved, actual, call_site = _resolved(
        tmp_path, "def make_guard(expected):\n    return len(expected)\n"
    )

    result = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=call_site
    )

    assert isinstance(result, ManagerConstructionGapV1)
    assert result.kind == "opaque-call-target"


def test_renamed_manager_protocol_retains_ordinary_method_call_frames(tmp_path):
    graph, resolved, actual, call_site = _resolved(
        tmp_path,
        "class ArbitraryGuard:\n"
        "    def __init__(self, marker):\n"
        "        self.marker = marker\n\n"
        "    def __enter__(self):\n"
        "        return self.marker\n\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        return self.marker\n\n"
        "def make_guard(marker):\n"
        "    return ArbitraryGuard(marker)\n",
    )
    behavior = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=call_site
    )
    assert isinstance(behavior, ConstructedManagerBehaviorV1)

    protocol = construct_manager_protocol(behavior, exit_face_id="fixture-face")

    assert isinstance(protocol, ConstructedManagerProtocolV1)
    assert protocol.enter_call.body is not None
    assert protocol.exit_call.body is not None
    assert protocol.enter_frame_cid.startswith("blake3-512:")
    assert protocol.exit_frame_cid.startswith("blake3-512:")
    assert protocol.protocol_construction_cid.startswith("blake3-512:")
    assert protocol.enter_call.formal_coordinate_cids
    enter_block = protocol.enter_call.force_floor(
        None, owner="renamed enter", project_callsite=False
    )
    exit_block = protocol.exit_call.force_floor(
        None, owner="renamed exit", project_callsite=False
    )
    assert isinstance(enter_block, BlockValue)
    assert isinstance(exit_block, BlockValue)
    assert enter_block.statements == (ReturnValue(actual.value),)
    assert exit_block.statements == (ReturnValue(actual.value),)


def test_manager_missing_source_protocol_method_stays_typed_loud(tmp_path):
    graph, resolved, actual, call_site = _resolved(
        tmp_path,
        "class ArbitraryObject:\n"
        "    def __init__(self, marker):\n"
        "        self.marker = marker\n\n"
        "def make_guard(marker):\n"
        "    return ArbitraryObject(marker)\n",
    )
    behavior = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=call_site
    )
    assert isinstance(behavior, ConstructedManagerBehaviorV1)

    protocol = construct_manager_protocol(behavior, exit_face_id="fixture-face")

    assert isinstance(protocol, ManagerProtocolConstructionGapV1)
    assert protocol.kind == "enter-missing"


def test_renamed_enter_and_exit_halts_remain_method_exitsets(tmp_path):
    graph, resolved, actual, call_site = _resolved(
        tmp_path,
        "class ArbitraryFailingGuard:\n"
        "    def __init__(self, marker):\n"
        "        self.marker = marker\n\n"
        "    def __enter__(self):\n"
        "        raise ValueError('enter')\n\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        raise TypeError('exit')\n\n"
        "def make_guard(marker):\n"
        "    return ArbitraryFailingGuard(marker)\n",
    )
    behavior = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=call_site
    )
    assert isinstance(behavior, ConstructedManagerBehaviorV1)
    protocol = construct_manager_protocol(behavior, exit_face_id="fixture-face")
    assert isinstance(protocol, ConstructedManagerProtocolV1)

    from sugar_lift_py_tests.outcome import ExitSet, Halted, outcome_to_exitset

    enter = outcome_to_exitset(protocol.enter_outcome())
    exit_ = outcome_to_exitset(protocol.exit_outcome())
    assert isinstance(enter, ExitSet)
    assert isinstance(exit_, ExitSet)
    assert all(isinstance(face, Halted) for face in enter.exits)
    assert all(isinstance(face, Halted) for face in exit_.exits)


def test_fixture_manager_class_bodies_construct_docstrings_and_class_fields():
    from sugar_lift_python_source.source_oracle import path_source
    from sugar_source_tree.nodes import ClassDef

    fixture = (
        Path(__file__).parents[2]
        / "sugar-lift-py-tests/tests/fixtures/with_source_derivation"
        / "arbitrary_manager_module.py"
    )
    source = SourceFile(path_source(str(fixture)))
    classes = {
        item.name: item for item in source.root.body if isinstance(item, ClassDef)
    }

    some_guard = classes["SomeGuard"].sugar().desugar().value
    some_resource = classes["SomeResource"].sugar().desugar().value
    lying_guard = classes["LyingGuard"].sugar().desugar().value
    observation = classes["ObservationSlot"].sugar().desugar().value

    assert some_guard.docstring_cid.startswith("blake3-512:")
    assert some_resource.docstring_cid.startswith("blake3-512:")
    assert lying_guard.docstring_cid.startswith("blake3-512:")
    fields = {field.name: field.value for field in lying_guard.class_fields}
    assert type(fields["claimed_suppression"]).__name__ == "TrueBoolLiteralSugar"
    assert observation.annotation_cids
    assert observation.decorator_cids


def test_renamed_manager_inter_method_call_uses_constructed_method_frame(tmp_path):
    graph, resolved, actual, call_site = _resolved(
        tmp_path,
        "class RenamedGuard:\n"
        "    def __init__(self, marker):\n"
        "        self.marker = marker\n\n"
        "    def project(self):\n"
        "        return self.marker\n\n"
        "    def __enter__(self):\n"
        "        return self.project()\n\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        return False\n\n"
        "def make_guard(marker):\n"
        "    return RenamedGuard(marker)\n",
    )
    behavior = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=call_site
    )
    assert isinstance(behavior, ConstructedManagerBehaviorV1)
    protocol = construct_manager_protocol(behavior, exit_face_id="fixture-face")
    assert isinstance(protocol, ConstructedManagerProtocolV1)

    enter_block = protocol.enter_call.force_floor(
        None, owner="inter-method enter", project_callsite=False
    )
    assert isinstance(enter_block, BlockValue)
    returned = enter_block.statements[0]
    assert isinstance(returned, ReturnValue)
    assert isinstance(returned.value, CallSiteValue)
    helper_block = returned.value.force_floor(None, owner="inter-method")
    assert isinstance(helper_block, BlockValue)
    assert helper_block.statements == (ReturnValue(actual.value),)


def test_source_factory_default_gets_authenticated_binding_testimony(tmp_path):
    graph, resolved, actual, call_site = _resolved(
        tmp_path,
        "class DefaultedGuard:\n"
        "    def __init__(self, marker, enabled):\n"
        "        self.marker = marker\n"
        "        self.enabled = enabled\n\n"
        "def make_guard(marker, *, enabled=False):\n"
        "    return DefaultedGuard(marker, enabled)\n",
    )

    behavior = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=call_site
    )

    assert isinstance(behavior, ConstructedManagerBehaviorV1)
    assert len(behavior.formal_actual_bindings) == 2
    assert all(
        entry.constructed_value_testimony is not None
        for entry in behavior.formal_actual_bindings
    )


def test_merged_renamed_some_guard_factory_constructs_through_sole_door(tmp_path):
    fixture = (
        Path(__file__).parents[2]
        / "sugar-lift-py-tests/tests/fixtures/with_source_derivation"
        / "arbitrary_manager_module.py"
    )
    graph, resolved, actual, call_site = _resolved(
        tmp_path, fixture.read_text(encoding="utf-8"), exported="some_manager"
    )

    behavior = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=call_site
    )

    assert isinstance(behavior, ConstructedManagerBehaviorV1)
    assert behavior.receiver_state.class_name == "SomeGuard"
    assert behavior.receiver_state.has_method("__enter__")
    assert behavior.receiver_state.has_method("__exit__")
    protocol = construct_manager_protocol(behavior, exit_face_id="fixture-face")
    assert isinstance(protocol, ConstructedManagerProtocolV1)
    assert protocol.enter_outcome() is not None
    assert protocol.exit_outcome() is not None


def test_renamed_resource_derives_never_suppresses_from_constructed_protocol(tmp_path):
    fixture = (
        Path(__file__).parents[2]
        / "sugar-lift-py-tests/tests/fixtures/with_source_derivation"
        / "arbitrary_manager_module.py"
    )
    graph, resolved, _actual, call_site = _resolved(
        tmp_path, fixture.read_text(encoding="utf-8"), exported="some_resource"
    )
    behavior = construct_manager_behavior(
        resolved, graph=graph, actuals=(), call_site=call_site
    )
    assert isinstance(behavior, ConstructedManagerBehaviorV1)
    protocol = construct_manager_protocol(behavior, exit_face_id="resource-face")
    assert isinstance(protocol, ConstructedManagerProtocolV1)

    summary = derive_manager_summary(protocol)

    from sugar_lift_py_tests.context_manager_contract import (
        NeverSuppressesDispositionV1,
        ProtocolResourceSemanticsV1,
    )

    assert isinstance(summary, DerivedManagerSummaryV1)
    assert isinstance(summary.semantics, ProtocolResourceSemanticsV1)
    assert isinstance(summary.semantics.exit.disposition, NeverSuppressesDispositionV1)
    assert summary.summary_cid.startswith("blake3-512:")


def test_opaque_suppression_predicate_stays_summary_gap(tmp_path):
    fixture = (
        Path(__file__).parents[2]
        / "sugar-lift-py-tests/tests/fixtures/with_source_derivation"
        / "arbitrary_manager_module.py"
    )
    graph, resolved, actual, call_site = _resolved(
        tmp_path, fixture.read_text(encoding="utf-8"), exported="some_manager"
    )
    behavior = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=call_site
    )
    assert isinstance(behavior, ConstructedManagerBehaviorV1)
    protocol = construct_manager_protocol(behavior, exit_face_id="boundary-face")
    assert isinstance(protocol, ConstructedManagerProtocolV1)

    summary = derive_manager_summary(protocol)

    assert isinstance(summary, DerivedManagerSummaryGapV1)
    assert summary.kind in {"enter-may-halt", "opaque-exit-truthiness"}


def test_source_derived_resource_ref_selects_projection_only_with_arm(tmp_path):
    fixture = (
        Path(__file__).parents[2]
        / "sugar-lift-py-tests/tests/fixtures/with_source_derivation"
        / "arbitrary_manager_module.py"
    )
    graph, resolved, _actual, call_site = _resolved(
        tmp_path, fixture.read_text(encoding="utf-8"), exported="some_resource"
    )
    behavior = construct_manager_behavior(
        resolved, graph=graph, actuals=(), call_site=call_site
    )
    protocol = construct_manager_protocol(behavior, exit_face_id="with-resource-face")
    summary = derive_manager_summary(protocol)
    assert isinstance(summary, DerivedManagerSummaryV1)

    from sugar_lift_py_tests.context_manager_resolution import (
        SourceDerivedContextManagerRefV1,
        SourceFragmentCoordinateV1,
        TreeConstructionContextV1,
    )
    from sugar_lift_py_tests.sugar.with_source_resource_sugar import (
        WithSourceResourceSugar,
    )
    from sugar_source_tree.nodes import With

    context = TreeConstructionContextV1.for_source_call_construction()
    consumer = (
        "def use_resource():\n"
        "    with resource_factory():\n"
        "        raise ValueError('body')\n"
    )
    tree = SourceFile(
        (consumer, "resource-consumer.py", "blake3-512:" + ("46" * 64)),
        construction_context=context,
    )
    node = next(item for item in tree.nodes() if isinstance(item, With))
    expr = node.items[0].context_expr
    span = expr.line_col_span()
    coordinate = SourceFragmentCoordinateV1(
        node.unit.source_cid,
        span.start_line,
        span.start_col,
        span.end_line,
        span.end_col,
    )
    context.source_derived_contract_refs[coordinate] = SourceDerivedContextManagerRefV1(
        coordinate, summary.summary_cid, summary.semantics, protocol
    )

    sugar = node.sugar()

    assert isinstance(sugar, WithSourceResourceSugar)
    assert sugar.protocol is protocol
    assert sugar.summary.summary_cid == summary.summary_cid
    from sugar_lift_py_tests.outcome import Halted, outcome_to_exitset

    routed = outcome_to_exitset(sugar.desugar())
    assert routed.exits
    assert any(isinstance(face, Halted) for face in routed.exits), [
        (type(face).__name__, repr(face.guard)) for face in routed.exits
    ]


def test_preconstruction_populates_resource_ref_from_authenticated_import(tmp_path):
    implementation = (
        "class RenamedResource:\n"
        "    def __enter__(self):\n"
        "        return 9\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        return False\n\n"
        "def make_resource():\n"
        "    return RenamedResource()\n"
    )
    distribution = _distribution(tmp_path, implementation, exported="make_resource")
    consumer = (
        "import arbitrary\n"
        "def use_resource():\n"
        "    with arbitrary.make_resource():\n"
        "        pass\n"
    )
    path = tmp_path / "consumer.py"
    path.write_text(consumer, encoding="utf-8")
    source_cid = blake3_512_of(consumer.encode("utf-8"))
    from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1

    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile((consumer, str(path), source_cid), construction_context=context)

    populate_source_derived_resource_refs(
        tree,
        root=tmp_path,
        path=path,
        distribution_index={"arbitrary": distribution},
    )

    from sugar_lift_py_tests.context_manager_resolution import (
        SourceDerivedContextManagerRefV1,
    )

    assert len(context.source_derived_contract_refs) == 1
    assert isinstance(
        next(iter(context.source_derived_contract_refs.values())),
        SourceDerivedContextManagerRefV1,
    )
